"""Generate diagnostic figure for the demo run."""

import sys

sys.path.insert(0, "/home/claude/dispersion_service")

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

OUT = Path("/home/claude/demo_output")
df = pd.read_csv(OUT / "demo_timeseries.csv", parse_dates=["hour"])

receptors = ["SAN YSIDRO", "NESTOR - BES", "IB CIVIC CTR"]
colors = {"SAN YSIDRO": "#e74c3c", "NESTOR - BES": "#2ecc71", "IB CIVIC CTR": "#3498db"}

fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
for ax, r in zip(axes, receptors, strict=False):
    ax.plot(df["hour"], df[f"obs_{r}"], "o-", color=colors[r], lw=1.5, ms=3, label="observed")
    ax.plot(
        df["hour"],
        df[f"pred_seed_{r}"],
        "--",
        color="gray",
        lw=1,
        alpha=0.7,
        label="predicted (seed rates)",
    )
    ax.plot(
        df["hour"],
        df[f"pred_fit_{r}"],
        "-",
        color="black",
        lw=1.5,
        alpha=0.8,
        label="predicted (fitted rates)",
    )
    ax.set_title(f"{r}", loc="left", fontsize=11)
    ax.set_ylabel("H₂S (ppb)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)

axes[-1].set_xlabel("Time (Pacific)")
fig.suptitle(
    "Demo run: Mar 13-15, 2026 (Stewart's Drain spill window)\n"
    "Forward Gaussian plume + NNLS inversion, 17 named sources",
    fontsize=12,
)
fig.tight_layout()
fig.savefig(OUT / "demo_timeseries.png", dpi=120, bbox_inches="tight")
print("Saved demo_timeseries.png")
