"""Fetch Sobol results to a local experiment folder.

The pipeline writes the aggregator in two places:

- **IO-manager pointer** (overwrites on every run) — the "latest run":
  - on NRP:  ``s3://<bucket>/dagster/runs/sobol_aggregate``
  - locally: the filesystem IO manager dir (``.dagster_io/`` by default)
- **Archival snapshot per run** (durable, set-once) — written by
  ``sobol_post_analysis`` to ``s3://<bucket>/runs/<tag>/`` where the
  tag is ``{window_start}_{window_end}_N{n}_seed{seed}_{date}``.
  Each contains ``sobol_indices.parquet``, ``analysis.json``, and
  ``summary.md``.

S3 mode is selected automatically when ``DAGSTER_S3_BUCKET`` +
``S3_ENDPOINT_URL`` + AWS creds are all present in the environment.
``--run-tag`` pulls a specific archival snapshot; otherwise the
"latest run" pointer is used (matches the actual S3PickleIOManager
layout we configure — historic versions of this script had a spurious
``run_id`` segment that didn't exist in the real key, which silently
fell through to filesystem mode).

Usage
-----
    # Pull the latest run (S3 if configured, else local filesystem IO):
    uv run python nrp/scripts/fetch_sobol_results.py

    # Pull a specific archived snapshot:
    uv run python nrp/scripts/fetch_sobol_results.py \\
        --run-tag 2026-03-13_2026-03-16_N8192_seed42_2026-05-22

    # Force the local filesystem path:
    uv run python nrp/scripts/fetch_sobol_results.py --force-local
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path
from typing import Any

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_LOCAL_IO = _REPO_ROOT / ".dagster_io"


def _records_to_frame(value: Any) -> pd.DataFrame:
    """The aggregator's value is ``{"indices": [records...]}``."""
    if isinstance(value, dict) and "indices" in value:
        return pd.DataFrame(value["indices"])
    raise ValueError(f"Unexpected aggregator payload shape: {type(value)} keys={list(value)[:5]}")


def _load_local(io_dir: Path) -> pd.DataFrame:
    """FilesystemIOManager pickles by asset key; unpartitioned asset →
    a file named ``sobol_aggregate``."""
    candidates = list(io_dir.rglob("sobol_aggregate*"))
    if not candidates:
        raise FileNotFoundError(
            f"No sobol_aggregate output under {io_dir}. Materialise it first "
            "(`uv run dg launch --assets sobol_aggregate`).",
        )
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    with newest.open("rb") as f:
        return _records_to_frame(pickle.load(f))


def _s3_client(endpoint_url: str | None) -> Any:
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
    )


def _load_s3_latest(bucket: str, endpoint_url: str | None) -> pd.DataFrame:
    """Read the IO-manager-keyed "latest run" pointer.

    The configured ``S3PickleIOManager`` keys the unpartitioned
    aggregate at ``<s3_prefix>/sobol_aggregate`` (no run_id segment —
    that was the old bug). Our prefix is ``dagster/runs``.
    """
    s3 = _s3_client(endpoint_url)
    key = "dagster/runs/sobol_aggregate"
    obj = s3.get_object(Bucket=bucket, Key=key)
    return _records_to_frame(pickle.loads(obj["Body"].read()))


def _load_s3_archive(bucket: str, endpoint_url: str | None, tag: str) -> pd.DataFrame:
    """Read the archival snapshot written by ``sobol_post_analysis``."""
    s3 = _s3_client(endpoint_url)
    key = f"runs/{tag}/sobol_indices.parquet"
    obj = s3.get_object(Bucket=bucket, Key=key)
    import io as _io

    return pd.read_parquet(_io.BytesIO(obj["Body"].read()))


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Sobol indices locally.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--dest",
        default="experiments/2026-05-15_sobol_full/output",
        help="destination folder (created if missing)",
    )
    ap.add_argument(
        "--run-tag",
        help=(
            "Archival snapshot tag "
            "(e.g. 2026-03-13_2026-03-16_N8192_seed42_2026-05-22). "
            "If omitted, fetches the 'latest run' IO-manager pointer."
        ),
    )
    ap.add_argument("--bucket", default=os.getenv("DAGSTER_S3_BUCKET"))
    ap.add_argument("--endpoint-url", default=os.getenv("S3_ENDPOINT_URL"))
    ap.add_argument(
        "--local-io-dir",
        default=os.getenv("DAGSTER_LOCAL_IO_DIR", str(_DEFAULT_LOCAL_IO)),
    )
    ap.add_argument(
        "--force-local",
        action="store_true",
        help="Skip S3 even if bucket+endpoint+creds are present.",
    )
    args = ap.parse_args()

    # Auto-detect S3 mode: needs bucket + endpoint + AWS creds. The old
    # script required --run-id to enter S3 mode, which never existed in
    # the actual S3 layout and silently fell through to filesystem.
    have_s3 = (
        not args.force_local
        and bool(args.bucket)
        and bool(args.endpoint_url)
        and bool(os.getenv("AWS_ACCESS_KEY_ID"))
        and bool(os.getenv("AWS_SECRET_ACCESS_KEY"))
    )

    if have_s3 and args.run_tag:
        src = f"s3://{args.bucket}/runs/{args.run_tag}/sobol_indices.parquet"
    elif have_s3:
        src = f"s3://{args.bucket}/dagster/runs/sobol_aggregate (latest run pointer)"
    else:
        src = f"{args.local_io_dir} (filesystem IO manager)"

    dest = _REPO_ROOT / args.dest if not Path(args.dest).is_absolute() else Path(args.dest)
    out = dest / "sobol_indices.csv"

    print("=== fetch sobol results ===")
    print(f"  source: {src}")
    print(f"  dest  : {out}")
    if args.dry_run:
        print("[dry-run] not fetching.")
        return 0

    try:
        if have_s3 and args.run_tag:
            df = _load_s3_archive(args.bucket, args.endpoint_url, args.run_tag)
        elif have_s3:
            df = _load_s3_latest(args.bucket, args.endpoint_url)
        else:
            df = _load_local(Path(args.local_io_dir))
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # boto ClientError etc — surface plainly without a stack
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    df.sort_values(["metric", "ST"], ascending=[True, False]).to_csv(out, index=False)
    print(f"wrote {len(df)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
