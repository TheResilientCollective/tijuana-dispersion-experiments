"""
Submit the full-scale Sobol sensitivity workload to NRP.

Per AGENTS.md NRP submission rules:
- Always accepts ``--dry-run``; the first call for a new workload must
  be ``--dry-run`` (a full sweep costs real compute).
- CI never auto-submits; this is always a deliberate human action.

What it does
------------
Materialises every partition of ``sobol_chunk_results`` (the K8s
fan-out) followed by ``sobol_aggregate``. Live submission requires a
running Dagster daemon and a kube context pointing at NRP — those, plus
the namespace / object-store / registry decisions, are the open
deployment questions in ``nrp/README.md``. ``--dry-run`` prints the
exact plan + command without touching the cluster so the pipeline can
be reviewed before any spend.

Usage
-----
    uv run python nrp/scripts/submit_sobol.py --dry-run            # always first
    uv run python nrp/scripts/submit_sobol.py --dry-run --n-base-samples 8192
    uv run python nrp/scripts/submit_sobol.py --n-base-samples 8192   # live (NRP)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Run-as-script: ensure the repo root (containing the `nrp` package) is
# importable regardless of CWD.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nrp.dagster_pipeline import N_SOBOL_CHUNKS
from nrp.sobol import PARAM_RANGES


def main() -> int:
    ap = argparse.ArgumentParser(description="Submit the Sobol sensitivity workload.")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, submit nothing")
    ap.add_argument(
        "--n-base-samples",
        type=int,
        default=8192,
        help="SALib base N; total samples = N*(D+2). Default 8192 (full scale).",
    )
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    d = len(PARAM_RANGES)
    total_samples = args.n_base_samples * (d + 2)
    rows_per_chunk = -(-total_samples // N_SOBOL_CHUNKS)  # ceil

    run_config = {
        "ops": {
            "sobol_chunk_results": {
                "config": {"n_base_samples": args.n_base_samples, "seed": args.seed}
            }
        }
    }

    print("=== Sobol submission plan ===")
    print(f"  parameters (D)       : {d}")
    print(f"  base samples (N)     : {args.n_base_samples}")
    print(f"  total samples N*(D+2): {total_samples:,}")
    print(f"  partitions (chunks)  : {N_SOBOL_CHUNKS}")
    print(f"  ~rows / chunk        : {rows_per_chunk:,}")
    print(f"  seed                 : {args.seed}")
    print("  asset graph          : sobol_chunk_results (fan-out) -> sobol_aggregate")
    print(f"  run config           : {run_config}")
    print()

    # Backfill all partitions, then the aggregator. On NRP the
    # k8s_job_executor turns each partition step into a K8s Job; that
    # requires the Dagster daemon + a kube context (see nrp/README.md
    # 'Decisions blocking deployment').
    backfill_cmd = [
        "dg",
        "launch",
        "--assets",
        "sobol_chunk_results",
        "--partition-range",
        f"chunk_000...chunk_{N_SOBOL_CHUNKS - 1:03d}",
    ]
    aggregate_cmd = ["dg", "launch", "--assets", "sobol_aggregate"]

    if args.dry_run:
        print("[dry-run] would run, in order:")
        print("  $", " ".join(backfill_cmd))
        print("  $", " ".join(aggregate_cmd))
        print(
            "\n[dry-run] NOT submitted. Resolve the open infra questions in "
            "nrp/README.md (namespace, object store, registry) and ensure a "
            "Dagster daemon + NRP kube context before a live run."
        )
        return 0

    if shutil.which("dg") is None:
        print("error: `dg` CLI not found on PATH (uv run dg ...).", file=sys.stderr)
        return 2

    print("Submitting (live). Requires Dagster daemon + NRP kube context…")
    for cmd in (backfill_cmd, aggregate_cmd):
        print("$", " ".join(cmd))
        rc = subprocess.call(cmd)
        if rc != 0:
            print(f"error: command failed (rc={rc}); aborting.", file=sys.stderr)
            return rc
    print("submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
