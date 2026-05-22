"""Submit the Sobol backfill via the Dagster GraphQL API (remote daemon).

This is the production submission path; the deprecated "plan-printer"
predecessor + the underscore-prefixed `_submit_backfill.py` working
copy used during the May 2026 NRP deployment have been consolidated
here.

Usage
-----
    # Full-scale production submission (default 8192 base samples):
    uv run python nrp/scripts/submit_sobol.py

    # Override sample count (e.g. quick smoke against a live daemon):
    uv run python nrp/scripts/submit_sobol.py --n-base-samples 256

    # Different fit window (multi-window Sobol):
    uv run python nrp/scripts/submit_sobol.py \\
        --window-start 2026-05-10 --window-end 2026-05-12

    # Dry-run (print the plan, don't submit):
    uv run python nrp/scripts/submit_sobol.py --dry-run

Requires a port-forward to the Dagster webserver:
    kubectl port-forward svc/dagster-webserver 3000:80 -n <ns>

This script launches the *partitioned* backfill of
``sobol_chunk_results``. After every chunk completes, materialize
``sobol_aggregate`` and ``sobol_post_analysis`` in a single follow-up
``dg launch`` against the same daemon — the submission summary at the
end of this script prints the exact command.
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
from nrp.sobol import DEFAULT_WINDOW, PARAM_RANGES

URL = "http://localhost:3000/graphql"

# Below this base sample count, Sobol indices are not converged
# (see experiments/2026-05-15_sobol_full/RESULTS.md). A submission
# accidentally at N=16 is what the 2026-05-21 NRP run was — the
# pipeline ran perfectly but produced unusable indices. This warning
# is the postmortem: a smoke-sized N must be deliberate, not silent.
SMOKE_THRESHOLD = 1024


def submit_backfill(
    n_base_samples: int,
    seed: int,
    window_start: str,
    window_end: str,
    dry_run: bool,
) -> str | None:
    d = len(PARAM_RANGES)
    total_samples = n_base_samples * (d + 2)
    rows_per_chunk = -(-total_samples // N_SOBOL_CHUNKS)

    scale_tag = "FULL-SCALE" if n_base_samples >= SMOKE_THRESHOLD else "SMOKE — NOT FOR SCIENCE"
    print("=== Sobol submission plan ===")
    print(f"  scale                : {scale_tag}")
    print(f"  parameters (D)       : {d}")
    print(f"  base samples (N)     : {n_base_samples}")
    print(f"  total samples N*(D+2): {total_samples:,}")
    print(f"  partitions (chunks)  : {N_SOBOL_CHUNKS}")
    print(f"  ~rows / chunk        : {rows_per_chunk:,}")
    print(f"  window               : {window_start} → {window_end}")
    print(f"  seed                 : {seed}")
    print()

    if n_base_samples < SMOKE_THRESHOLD:
        print(
            f"!! WARNING: N={n_base_samples} is below {SMOKE_THRESHOLD} — Sobol indices will\n"
            "   not be converged at this scale (the May 2026 first run hit this exactly).\n"
            "   Pass --n-base-samples 8192 for a publishable result.\n",
            file=sys.stderr,
        )

    if dry_run:
        print("[dry-run] NOT submitted.")
        return None

    partitions = [f"chunk_{i:03d}" for i in range(N_SOBOL_CHUNKS)]

    # Pass run config so the chunk asset uses the requested params
    # instead of SobolConfig's tiny local-dev default. The same window
    # config flows to sobol_post_analysis (which reads SobolConfig too).
    run_config_yaml = json.dumps(
        {
            "ops": {
                "sobol_chunk_results": {
                    "config": {
                        "n_base_samples": n_base_samples,
                        "seed": seed,
                        "window_start": window_start,
                        "window_end": window_end,
                    },
                },
            },
        },
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
        ... on LaunchBackfillSuccess { backfillId }
        ... on PythonError { message }
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


def _follow_up_hint(window_start: str, window_end: str, n: int, seed: int) -> None:
    print("\nNext steps once every chunk has completed:")
    config = {
        "ops": {
            "sobol_post_analysis": {
                "config": {
                    "n_base_samples": n,
                    "seed": seed,
                    "window_start": window_start,
                    "window_end": window_end,
                },
            },
        },
    }
    print(
        "  # In the same daemon context, materialise the aggregator + post-analysis:\n"
        "  dg launch --assets sobol_aggregate,sobol_post_analysis \\\n"
        f"    --config '{json.dumps(config)}'",
    )
    print(
        "\n  # When sobol_post_analysis succeeds, the run-scoped archive lands at:\n"
        f"  s3://$DAGSTER_S3_BUCKET/runs/"
        f"{window_start}_{window_end}_N{n}_seed{seed}_<run-date>/",
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Submit Sobol backfill via Dagster GraphQL API.")
    ap.add_argument(
        "--n-base-samples",
        type=int,
        default=8192,
        help="SALib base N; total = N*(D+2). Default 8192 (production / publishable).",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--window-start",
        default=DEFAULT_WINDOW[0],
        help=f"Fit-window start (inclusive). Default {DEFAULT_WINDOW[0]}.",
    )
    ap.add_argument(
        "--window-end",
        default=DEFAULT_WINDOW[1],
        help=f"Fit-window end (exclusive). Default {DEFAULT_WINDOW[1]}.",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, don't submit.")
    args = ap.parse_args()

    backfill_id = submit_backfill(
        args.n_base_samples,
        args.seed,
        args.window_start,
        args.window_end,
        args.dry_run,
    )
    if backfill_id:
        print(f"\nBackfill submitted: {backfill_id}")
        _follow_up_hint(args.window_start, args.window_end, args.n_base_samples, args.seed)
    elif not args.dry_run:
        sys.exit(1)
