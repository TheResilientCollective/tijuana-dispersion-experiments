"""Sensitivity heatmap: parameters × metrics, |Pearson r|."""

import sys

sys.path.insert(0, "/home/claude/dispersion_service")

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path("/home/claude/sensitivity_output")
sens = pd.read_csv(OUT / "sensitivities.csv")

# Pivot to matrix: parameters (rows) × metrics (cols)
metric_order = []
for kind in ["corr", "rms", "peak_ratio"]:
    for r in ["SAN YSIDRO", "NESTOR - BES", "IB CIVIC CTR"]:
        metric_order.append(f"{kind}_{r}")

# Use signed r (not abs) so sign is visible
mat = sens.pivot(index="parameter", columns="metric", values="pearson_r")
mat = mat.reindex(columns=metric_order)

param_order = [
    "baseline_scale",
    "f_arch_drain",
    "f_arch_channel",
    "f_arch_estuary",
    "f_arch_bay",
    "Q10",
    "T_ref_c",
    "substrate_alpha",
    "substrate_threshold",
    "diel_amplitude",
    "diel_phase_hours",
]
mat = mat.reindex(index=param_order)

fig, ax = plt.subplots(figsize=(11, 6))
im = ax.imshow(mat.values, cmap="RdBu_r", vmin=-0.7, vmax=0.7, aspect="auto")
ax.set_xticks(range(len(metric_order)))
ax.set_xticklabels([c.replace("_", "\n", 1) for c in metric_order], rotation=0, fontsize=8)
ax.set_yticks(range(len(param_order)))
ax.set_yticklabels(param_order, fontsize=9)

# Annotate cells with values
for i in range(len(param_order)):
    for j in range(len(metric_order)):
        v = mat.values[i, j]
        if not np.isnan(v):
            color = "white" if abs(v) > 0.4 else "black"
            ax.text(j, i, f"{v:+.2f}", ha="center", va="center", fontsize=7, color=color)

# Vertical separators between metric groups
for x in [2.5, 5.5]:
    ax.axvline(x, color="black", lw=1.5)

cbar = plt.colorbar(im, ax=ax, fraction=0.025)
cbar.set_label("Pearson r")
ax.set_title(
    "Emissions parameter sensitivity (200-sample LHS, Mar 13-15 window)\n"
    "Larger |r| = parameter more strongly influences that metric",
    fontsize=11,
)
fig.tight_layout()
fig.savefig(OUT / "sensitivity_heatmap.png", dpi=130, bbox_inches="tight")
print("Saved sensitivity_heatmap.png")
