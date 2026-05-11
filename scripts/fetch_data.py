"""
Fetch declared data sources to ./data/.

Reads `data/manifest.yaml` and downloads each dataset with checksum
verification. Refuses to silently substitute fake or zero data when a
fetch fails — raises instead. (No-synthetic-data rule from AGENTS.md.)

Usage:
    uv run python scripts/fetch_data.py
    uv run python scripts/fetch_data.py --only modeldata_h2s_nofill
    uv run python scripts/fetch_data.py --update-checksums
    uv run python scripts/fetch_data.py --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import sys
from pathlib import Path

import requests
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.yaml"


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while data := f.read(chunk):
            h.update(data)
    return h.hexdigest()


def fetch_one(dataset: dict, dry_run: bool = False) -> str:
    """Fetch one dataset. Returns sha256 of the downloaded file. Raises on failure."""
    name = dataset["name"]
    target = ROOT / dataset["target_path"]
    target.parent.mkdir(parents=True, exist_ok=True)

    urls = [dataset["url"]]
    if "fallback_url" in dataset:
        urls.append(dataset["fallback_url"])

    if dry_run:
        log.info("[dry-run] would fetch %s -> %s", urls[0], target)
        return "dry-run"

    last_error: Exception | None = None
    for url in urls:
        try:
            log.info("fetching %s from %s", name, url)
            with requests.get(url, stream=True, timeout=120) as resp:
                resp.raise_for_status()
                with target.open("wb") as f:
                    for chunk in resp.iter_content(1 << 20):
                        f.write(chunk)
            actual_size = target.stat().st_size
            expected_mb = dataset.get("expected_size_mb")
            if expected_mb and actual_size < expected_mb * 1_000_000 * 0.1:
                # Likely an HTML error page rather than the real file
                raise RuntimeError(
                    f"{name}: downloaded {actual_size} bytes, expected ~{expected_mb} MB. "
                    f"Probably an upstream redirect or auth wall."
                )
            sha = sha256_file(target)
            log.info("fetched %s (%s bytes, sha256=%s)", name, actual_size, sha[:12])
            return sha
        except Exception as e:
            log.warning("fetch failed for %s: %s", url, e)
            last_error = e
            if target.exists():
                target.unlink()
            continue

    # All URLs failed. Raise — do NOT return placeholder data.
    raise RuntimeError(
        f"All URLs failed for dataset '{name}'. Last error: {last_error}. "
        "Aborting. (Reproducibility rule: no synthetic data fallbacks.)"
    )


def verify_checksum(dataset: dict, sha: str) -> None:
    expected = dataset.get("sha256")
    if not expected or expected == "pending":
        return
    if expected == sha:
        return
    msg = (
        f"{dataset['name']}: sha256 mismatch! "
        f"manifest says {expected}, file is {sha}. "
        "Either upstream data changed or your manifest is stale."
    )
    if dataset.get("strict", False):
        raise RuntimeError(msg)
    else:
        log.warning("%s (non-strict; continuing)", msg)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="fetch only this dataset name (default: all)")
    parser.add_argument(
        "--update-checksums",
        action="store_true",
        help="rewrite manifest with sha256 of fetched files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be fetched without downloading",
    )
    args = parser.parse_args()

    manifest = yaml.safe_load(MANIFEST_PATH.read_text())
    targets = manifest["datasets"]
    if args.only:
        targets = [d for d in targets if d["name"] == args.only]
        if not targets:
            log.error("no dataset named %s in manifest", args.only)
            return 1

    sums: dict[str, str] = {}
    for dataset in targets:
        sha = fetch_one(dataset, dry_run=args.dry_run)
        if not args.dry_run:
            verify_checksum(dataset, sha)
        sums[dataset["name"]] = sha

    if args.update_checksums and not args.dry_run:
        for dataset in manifest["datasets"]:
            if dataset["name"] in sums:
                dataset["sha256"] = sums[dataset["name"]]
        MANIFEST_PATH.write_text(yaml.safe_dump(manifest, sort_keys=False))
        log.info("updated %s with new checksums", MANIFEST_PATH)

    log.info("done; %d datasets processed", len(targets))
    return 0


if __name__ == "__main__":
    sys.exit(main())
