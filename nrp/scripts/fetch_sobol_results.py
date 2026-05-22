"""Fetch the Sobol aggregator's indices to a local experiment folder.

The ``sobol_aggregate`` asset persists via the IO manager:
- on NRP: S3 at ``s3://<bucket>/dagster/runs/<run_id>/sobol_aggregate*``
- locally: the filesystem IO manager dir (``.dagster_io/`` by default)

This script reads whichever is configured and writes a tidy
``sobol_indices.csv`` (parameter × metric × S1/ST) into the destination
experiment folder. Accepts ``--dry-run``.

Usage
-----
    uv run python nrp/scripts/fetch_sobol_results.py --dry-run
    uv run python nrp/scripts/fetch_sobol_results.py \
        --dest experiments/2026-05-15_sobol_full/output
    uv run python nrp/scripts/fetch_sobol_results.py \
        --run-id <run> --bucket <bucket> --endpoint-url https://oss...
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
    """The aggregator's value is {'indices': [records...]}."""
    if isinstance(value, dict) and "indices" in value:
        return pd.DataFrame(value["indices"])
    raise ValueError(f"Unexpected aggregator payload shape: {type(value)} keys={list(value)[:5]}")


def _load_local(io_dir: Path) -> pd.DataFrame:
    # FilesystemIOManager pickles by asset key; unpartitioned asset →
    # a file named 'sobol_aggregate'.
    candidates = list(io_dir.rglob("sobol_aggregate*"))
    if not candidates:
        raise FileNotFoundError(
            f"No sobol_aggregate output under {io_dir}. Materialise it first "
            "(`uv run dg launch --assets sobol_aggregate`).",
        )
    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    with newest.open("rb") as f:
        return _records_to_frame(pickle.load(f))


def _load_s3(bucket: str, run_id: str, endpoint_url: str | None) -> pd.DataFrame:
    import boto3  # only needed for the S3 path

    s3 = boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        region_name=os.getenv("AWS_DEFAULT_REGION"),
    )
    prefix = f"dagster/runs/{run_id}/sobol_aggregate"
    listing = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    contents = listing.get("Contents", [])
    if not contents:
        raise FileNotFoundError(f"s3://{bucket}/{prefix}* not found.")
    key = sorted(c["Key"] for c in contents)[-1]
    obj = s3.get_object(Bucket=bucket, Key=key)
    return _records_to_frame(pickle.loads(obj["Body"].read()))


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch Sobol indices locally.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--dest",
        default="experiments/2026-05-15_sobol_full/output",
        help="destination folder (created if missing)",
    )
    ap.add_argument("--run-id", help="NRP run id (S3 mode)")
    ap.add_argument("--bucket", default=os.getenv("DAGSTER_S3_BUCKET"))
    ap.add_argument("--endpoint-url", default=os.getenv("S3_ENDPOINT_URL"))
    ap.add_argument(
        "--local-io-dir",
        default=os.getenv("DAGSTER_LOCAL_IO_DIR", str(_DEFAULT_LOCAL_IO)),
    )
    args = ap.parse_args()

    use_s3 = bool(args.run_id and args.bucket)
    src = (
        f"s3://{args.bucket}/dagster/runs/{args.run_id}/sobol_aggregate*"
        if use_s3
        else f"{args.local_io_dir} (filesystem IO manager)"
    )
    dest = _REPO_ROOT / args.dest if not Path(args.dest).is_absolute() else Path(args.dest)
    out = dest / "sobol_indices.csv"

    print("=== fetch sobol results ===")
    print(f"  source: {src}")
    print(f"  dest  : {out}")
    if args.dry_run:
        print("[dry-run] not fetching.")
        return 0

    try:
        df = (
            _load_s3(args.bucket, args.run_id, args.endpoint_url)
            if use_s3
            else _load_local(Path(args.local_io_dir))
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    dest.mkdir(parents=True, exist_ok=True)
    df.sort_values(["metric", "ST"], ascending=[True, False]).to_csv(out, index=False)
    print(f"wrote {len(df)} rows -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
