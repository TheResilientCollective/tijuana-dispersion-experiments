"""Submit the Sobol backfill via the Dagster GraphQL API (remote daemon).

Usage:
    # Default 8192 base samples (full scale):
    uv run python nrp/scripts/_submit_backfill.py

    # Custom sample count:
    uv run python nrp/scripts/_submit_backfill.py --n-base-samples 256

    # Dry-run (print the plan, don't submit):
    uv run python nrp/scripts/_submit_backfill.py --dry-run
    uv run python nrp/scripts/_submit_backfill.py --dry-run --n-base-samples 1024

Requires a port-forward to the Dagster webserver on localhost:3000.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

# Ensure the repo root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nrp.dagster_pipeline import N_SOBOL_CHUNKS
from nrp.sobol import PARAM_RANGES

URL = "http://localhost:3000/graphql"


def submit_backfill(n_base_samples: int, seed: int, dry_run: bool) -> str | None:
    d = len(PARAM_RANGES)
    total_samples = n_base_samples * (d + 2)
    rows_per_chunk = -(-total_samples // N_SOBOL_CHUNKS)

    print("=== Sobol submission plan ===")
    print(f"  parameters (D)       : {d}")
    print(f"  base samples (N)     : {n_base_samples}")
    print(f"  total samples N*(D+2): {total_samples:,}")
    print(f"  partitions (chunks)  : {N_SOBOL_CHUNKS}")
    print(f"  ~rows / chunk        : {rows_per_chunk:,}")
    print(f"  seed                 : {seed}")
    print()

    if dry_run:
        print("[dry-run] NOT submitted.")
        return None

    partitions = [f"chunk_{i:03d}" for i in range(N_SOBOL_CHUNKS)]

    # Pass run config so the asset uses the requested n_base_samples/seed
    # instead of the tiny default (16).
    run_config_yaml = json.dumps(
        {
            "ops": {
                "sobol_chunk_results": {
                    "config": {
                        "n_base_samples": n_base_samples,
                        "seed": seed,
                    }
                }
            }
        }
    )

    mutation = """
    mutation($partitions: [String!]!, $runConfigData: RunConfigData) {
      launchPartitionBackfill(
        backfillParams: {
          partitionNames: $partitions,
          assetSelection: [{ path: ["sobol_chunk_results"] }],
          runConfigData: $runConfigData,
        }
      ) {
        ... on LaunchBackfillSuccess {
          backfillId
        }
        ... on PythonError {
          message
        }
      }
    }
    """

    resp = requests.post(
        URL,
        json={
            "query": mutation,
            "variables": {"partitions": partitions, "runConfigData": run_config_yaml},
        },
    )
    result = resp.json()
    print(json.dumps(result, indent=2))

    data = (result.get("data") or {}).get("launchPartitionBackfill", {})
    if "backfillId" in data:
        return data["backfillId"]
    print(f"Error: {data.get('message', 'unknown')}", file=sys.stderr)
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Submit Sobol backfill via Dagster GraphQL API.")
    ap.add_argument(
        "--n-base-samples",
        type=int,
        default=8192,
        help="SALib base N; total = N*(D+2). Default 8192 (full scale).",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, don't submit.")
    args = ap.parse_args()

    backfill_id = submit_backfill(args.n_base_samples, args.seed, args.dry_run)
    if backfill_id:
        print(f"\nBackfill submitted: {backfill_id}")
    elif not args.dry_run:
        sys.exit(1)
