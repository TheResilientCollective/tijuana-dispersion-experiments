"""
Local reduced-N Sobol run (issue #2).

Exercises the *same* science as the NRP pipeline
(`nrp/sobol.py`) without Dagster/K8s, at a small base-N so it finishes
locally in minutes. Produces a real Sobol indices table to (a) prove
the workload end-to-end and (b) compare the parameter ranking against
the 2026-05-05 LHS Pearson proxy.

This is NOT the full-scale production run (N=8192, ~106k samples) — that
requires NRP (see nrp/README.md "Decisions blocking deployment").

Reproduce:
    uv run python experiments/2026-05-15_sobol_full/run.py --n-base 24
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nrp import sobol

HERE = Path(__file__).parent
OUT = HERE / "output"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-base", type=int, default=24, help="SALib base N (small for local)")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    problem = sobol.build_problem()
    samples = sobol.build_samples(args.n_base, seed=args.seed)
    print(f"D={problem['num_vars']}  N={args.n_base}  total samples={samples.shape[0]}")

    df = sobol.load_window(sobol.DEFAULT_PARQUET, sobol.DEFAULT_WINDOW)
    drivers, met, hours = sobol.make_drivers_and_met(df)
    obs = sobol.build_obs(df, hours, sobol.RECEPTOR_NAMES)
    print(f"window {sobol.DEFAULT_WINDOW}: {len(drivers)} hours")

    t0 = time.time()
    rows: list[dict[str, float]] = []
    for i in range(samples.shape[0]):
        m = sobol.evaluate_sample(samples[i], problem["names"], drivers, met, obs)
        rows.append({"_row": i, **m})
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{samples.shape[0]} ({time.time() - t0:.0f}s)")
    print(f"evaluated {len(rows)} samples in {time.time() - t0:.0f}s")

    # Reassemble (single 'chunk') and analyse every metric column.
    asm = sobol.reassemble(
        {
            "chunk_000": {
                "start": 0,
                "end": samples.shape[0],
                "param_names": problem["names"],
                "metric_columns": sobol.OUTPUT_COLUMNS,
                "rows": rows,
            }
        }
    )
    frames = []
    for metric, y in asm["y_by_metric"].items():
        if np.isnan(y).any():
            continue
        r = sobol.analyze(problem, y)
        r.insert(0, "metric", metric)
        frames.append(r)
    indices = pd.concat(frames, ignore_index=True)
    indices.to_csv(OUT / "sobol_indices.csv", index=False)

    top = indices.sort_values("ST", ascending=False).head(10)
    summary = {
        "n_base": args.n_base,
        "total_samples": int(samples.shape[0]),
        "window": list(sobol.DEFAULT_WINDOW),
        "n_hours": len(drivers),
        "metrics_analysed": sorted({m for m in indices["metric"]}),
        "top10_by_ST": top[["metric", "parameter", "S1", "ST"]].to_dict("records"),
        "runtime_s": round(time.time() - t0, 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print("\nTop 10 by total-order ST:")
    print(top[["metric", "parameter", "S1", "ST"]].to_string(index=False))
    print(f"\nartifacts -> {OUT}")


if __name__ == "__main__":
    main()
