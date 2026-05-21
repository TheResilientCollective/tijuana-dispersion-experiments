"""Comparison plot: demo (v1) vs calibration v2."""

import sys

sys.path.insert(0, "/home/claude/dispersion_service")

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

V1 = Path("/home/claude/demo_output")
V2 = Path("/home/claude/calibration_v2_output")
OUT = Path("/home/claude/calibration_v2_output")

v1 = pd.read_csv(V1 / "demo_timeseries.csv", parse_dates=["hour"])
v2 = pd.read_csv(V2 / "timeseries.csv", parse_dates=["hour"])

receptors = ["SAN YSIDRO", "NESTOR - BES", "IB CIVIC CTR"]
colors = {"SAN YSIDRO": "#e74c3c", "NESTOR - BES": "#2ecc71", "IB CIVIC CTR": "#3498db"}

fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
for ax, r in zip(axes, receptors, strict=False):
    ax.plot(
        v2["hour"],
        v2[f"obs_{r}"],
        "o-",
        color=colors[r],
        lw=2,
        ms=4,
        label="observed",
        zorder=3,
    )
    ax.plot(
        v1["hour"],
        v1[f"pred_fit_{r}"],
        "--",
        color="gray",
        lw=1.2,
        alpha=0.7,
        label="v1: 17 named sources, unconstrained NNLS",
    )
    ax.plot(
        v2["hour"],
        v2[f"pred_{r}"],
        "-",
        color="black",
        lw=1.5,
        alpha=0.85,
        label="v2: +12 channel +9 estuary, archetype-bounded",
    )

    # Compute correlations for legend annotation
    valid_v1 = ~v1[f"obs_{r}"].isna()
    valid_v2 = ~v2[f"obs_{r}"].isna()
    r_v1 = np.corrcoef(v1.loc[valid_v1, f"pred_fit_{r}"], v1.loc[valid_v1, f"obs_{r}"])[0, 1]
    r_v2 = np.corrcoef(v2.loc[valid_v2, f"pred_{r}"], v2.loc[valid_v2, f"obs_{r}"])[0, 1]
    ax.text(
        0.99,
        0.95,
        f"v1 r = {r_v1:.2f}\nv2 r = {r_v2:.2f}",
        transform=ax.transAxes,
        ha="right",
        va="top",
        fontsize=9,
        family="monospace",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85),
    )

    ax.set_title(f"{r}", loc="left", fontsize=11)
    ax.set_ylabel("H₂S (ppb)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)

axes[-1].set_xlabel("Time (Pacific)")
fig.suptitle(
    "Calibration v1 vs v2 — Mar 13-15, 2026 (Stewart's Drain spill window)",
    fontsize=12,
)
fig.tight_layout()
fig.savefig(OUT / "v1_vs_v2.png", dpi=120, bbox_inches="tight")
print("Saved v1_vs_v2.png")
