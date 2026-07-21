"""HYSPLIT ARL meteorology acquisition — pluggable, cache-through.

Both supported datasets live in the NOAA ARL AWS Open Data archive
``s3://noaa-oar-arl-hysplit-pds`` (us-east-1, anonymous):

- ``hrrr`` (default): 3 km CONUS, 6-hour chunks of ~3.4 GB at
  ``hrrr/{YYYY}/{MM}/{YYYYMMDD}_{00-05|06-11|12-17|18-23}_hrrr`` — the right
  resolution for the ~880 m Saturn→Nestor problem.
- ``gdas1``: 1° weekly files (~600 MB) at ``gdas1/{YYYY}/gdas1.{mon}{yy}.w{n}`` —
  cheap smoke tests / fallback.

``ensure_met_files`` resolves each file through a chain, first hit wins:

1. pre-seeded ``met_dir`` (``$HYSPLIT_METEO_DIR`` PVC/host mount, or a
   manually staged higher-resolution dataset such as the 1 km Globus archive);
2. an NRP Ceph S3 mirror (``MET_MIRROR_ENDPOINT/BUCKET/KEY/SECRET``), with
   pull-through: on mirror miss the file is first streamed AWS→mirror, then
   mirror→``met_dir`` — the per-file "rsync before access" pattern;
3. the OSDF/Pelican federation (``pelican`` client on PATH; the
   ``/aws-opendata/us-east-1`` namespace is federated and token-free) —
   opportunistic, falls through on any failure;
4. direct anonymous HTTPS from the AWS bucket — always available.

Per AGENTS.md nothing is fabricated: if every path fails, this raises.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

log = logging.getLogger(__name__)

AWS_BUCKET = "noaa-oar-arl-hysplit-pds"
AWS_HTTPS_BASE = f"https://{AWS_BUCKET}.s3.amazonaws.com"
OSDF_PREFIX = f"osdf:///aws-opendata/us-east-1/{AWS_BUCKET}"

MET_SOURCES = ("hrrr", "gdas1")

#: Size sanity floor per dataset (bytes) — a smaller file is a truncated
#: download, not a cache hit. HRRR chunks are ~3.4 GB; GDAS1 weeks ~600 MB.
_MIN_BYTES = {"hrrr": 1_000_000_000, "gdas1": 100_000_000}

_HRRR_BLOCKS = ((0, "00-05"), (6, "06-11"), (12, "12-17"), (18, "18-23"))


@dataclass(frozen=True)
class MetFile:
    """One ARL met file: local/CONTROL filename + its AWS S3 key."""

    name: str
    key: str
    min_bytes: int


def _gdas1_name(dt_utc: pd.Timestamp) -> str:
    week = (dt_utc.day - 1) // 7 + 1
    return f"gdas1.{dt_utc.strftime('%b').lower()}{dt_utc.strftime('%y')}.w{week}"


def met_files_for(met_source: str, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> list[MetFile]:
    """Ordered, de-duplicated met files covering [start_utc, end_utc].

    Callers must already include the backward reach / forward spin-up in the
    interval. Handles month and week-5 boundaries.
    """
    if met_source not in MET_SOURCES:
        raise ValueError(f"Unknown met_source {met_source!r}; expected one of {MET_SOURCES}")
    if end_utc < start_utc:
        raise ValueError("end_utc before start_utc")
    out: list[MetFile] = []
    seen: set[str] = set()
    min_bytes = _MIN_BYTES[met_source]
    day = start_utc.floor("D")
    while day <= end_utc:
        if met_source == "gdas1":
            name = _gdas1_name(day)
            # The archive nests weekly files under the year: gdas1/2026/gdas1.apr26.w1
            key = f"gdas1/{day.strftime('%Y')}/{name}"
            if name not in seen:
                seen.add(name)
                out.append(MetFile(name, key, min_bytes))
        else:
            for block_start, block in _HRRR_BLOCKS:
                block_t = day + pd.Timedelta(hours=block_start)
                if block_t + pd.Timedelta(hours=6) <= start_utc or block_t > end_utc:
                    continue
                name = f"{day.strftime('%Y%m%d')}_{block}_hrrr"
                key = f"hrrr/{day.strftime('%Y')}/{day.strftime('%m')}/{name}"
                if name not in seen:
                    seen.add(name)
                    out.append(MetFile(name, key, min_bytes))
        day += pd.Timedelta(days=1)
    return out


def resolve_met_dir(config_met_dir: str | None) -> Path:
    """Config value → $HYSPLIT_METEO_DIR/$HYSPLIT_MET_DIR → repo-local ./met."""
    if config_met_dir:
        return Path(config_met_dir)
    for var in ("HYSPLIT_METEO_DIR", "HYSPLIT_MET_DIR"):
        if os.getenv(var):
            return Path(os.environ[var])
    return Path(__file__).resolve().parent.parent / "met"


def _present(path: Path, min_bytes: int) -> bool:
    return path.exists() and path.stat().st_size >= min_bytes


def _stream_to(resp: requests.Response, dest: Path) -> None:
    part = dest.with_suffix(dest.suffix + ".part")
    with open(part, "wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
    part.replace(dest)


def _fetch_https(mf: MetFile, dest: Path, retries: int = 4) -> None:
    url = f"{AWS_HTTPS_BASE}/{mf.key}"
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with requests.get(url, stream=True, timeout=(30, 300)) as resp:
                resp.raise_for_status()
                _stream_to(resp, dest)
            if not _present(dest, mf.min_bytes):
                raise OSError(f"{dest} smaller than sanity floor after download")
            return
        except Exception as exc:  # broad on purpose: retried, re-raised on exhaustion
            if attempt == retries:
                raise
            log.warning("HTTPS fetch of %s failed (%s); retrying in %.0fs", mf.name, exc, delay)
            time.sleep(delay)
            delay *= 2


def _fetch_pelican(mf: MetFile, dest: Path) -> bool:
    """Opportunistic OSDF pull; True on success, False to fall through."""
    if shutil.which("pelican") is None:
        return False
    part = dest.with_suffix(dest.suffix + ".part")
    try:
        subprocess.run(
            ["pelican", "object", "get", f"{OSDF_PREFIX}/{mf.key}", str(part)],
            check=True,
            capture_output=True,
            timeout=3600,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        log.warning("pelican fetch of %s failed (%s); falling through", mf.name, exc)
        part.unlink(missing_ok=True)
        return False
    if part.stat().st_size < mf.min_bytes:
        part.unlink(missing_ok=True)
        return False
    part.replace(dest)
    return True


def _mirror_client():
    """boto3 client for the optional NRP Ceph S3 mirror, or None if unset."""
    endpoint = os.getenv("MET_MIRROR_ENDPOINT")
    bucket = os.getenv("MET_MIRROR_BUCKET")
    if not endpoint or not bucket:
        return None, None
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.getenv("MET_MIRROR_KEY"),
        aws_secret_access_key=os.getenv("MET_MIRROR_SECRET"),
    )
    return client, bucket


def _fetch_via_mirror(mf: MetFile, dest: Path) -> bool:
    """Pull-through the Ceph mirror; True on success, False to fall through."""
    client, bucket = _mirror_client()
    if client is None:
        return False
    try:
        try:
            client.head_object(Bucket=bucket, Key=mf.key)
        except client.exceptions.ClientError:
            log.info("mirror miss for %s — streaming AWS → mirror", mf.name)
            with requests.get(f"{AWS_HTTPS_BASE}/{mf.key}", stream=True, timeout=(30, 300)) as r:
                r.raise_for_status()
                client.upload_fileobj(r.raw, bucket, mf.key)
        part = dest.with_suffix(dest.suffix + ".part")
        client.download_file(bucket, mf.key, str(part))
        if part.stat().st_size < mf.min_bytes:
            part.unlink(missing_ok=True)
            return False
        part.replace(dest)
        return True
    except Exception as exc:  # broad on purpose: mirror is optional; HTTPS is the backstop
        log.warning("mirror fetch of %s failed (%s); falling through", mf.name, exc)
        return False


def ensure_met_files(met_files: list[MetFile], met_dir: Path) -> Path:
    """Make every met file present in ``met_dir``; returns ``met_dir``.

    Resolution chain per file: already present → Ceph mirror (pull-through) →
    OSDF/pelican → direct AWS HTTPS. Raises if a file cannot be obtained.
    """
    met_dir.mkdir(parents=True, exist_ok=True)
    for mf in met_files:
        dest = met_dir / mf.name
        if _present(dest, mf.min_bytes):
            log.info("met file %s already present", mf.name)
            continue
        if _fetch_via_mirror(mf, dest) or _fetch_pelican(mf, dest):
            log.info("fetched %s (%.1f GB)", mf.name, dest.stat().st_size / 1e9)
            continue
        log.info("fetching %s directly from %s", mf.name, AWS_HTTPS_BASE)
        _fetch_https(mf, dest)
        log.info("fetched %s (%.1f GB)", mf.name, dest.stat().st_size / 1e9)
    return met_dir
