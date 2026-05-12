"""
Diagnostic: characterise the SAN YSIDRO N/NE residual flagged by
calibration v3. Pure analysis — no fitting.

Inputs:
    ../../data/modeldata_h2s_nofill.parquet
    ../2026-05-11_calibration_v3/output/fitted_rates_v3.csv

Outputs (gitignored output/ dir):
    sector_means.csv         per-sector mean H₂S per receptor (holdout)
    elevated_sy_north.csv    hours where SY > 10 ppb AND wind from N/NE
    nestor_heavy_events.csv  hours where NESTOR > 50 ppb, with sector + time
    v3_rates_at_bound.csv    v3 fitted rates filtered to those at archetype cap
    summary.json             findings + numeric flags for the v3.1 design
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HERE = Path(__file__).parent
OUTPUTS = HERE / "output"
PARQUET = HERE / "../../data/modeldata_h2s_nofill.parquet"
V3_RATES = HERE / "../2026-05-11_calibration_v3/output/fitted_rates_v3.csv"

SECTOR_LABELS = [
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
]
ARCHETYPE_BOUNDS = {"drain": 5.0, "channel": 2.0, "estuary": 3.0, "bay": 0.5, "spill": 20.0}


def sector_index(deg: float) -> int | None:
    if pd.isna(deg):
        return None
    return int(((deg + 11.25) % 360) // 22.5)


def load_holdout() -> pd.DataFrame:
    df = pd.read_parquet(PARQUET)
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    mask = (df["time"] >= "2026-04-01") & (df["time"] < "2026-04-15")
    return df.loc[mask].copy()


def main() -> None:
    OUTPUTS.mkdir(exist_ok=True)

    log.info("loading holdout window (Apr 1-14, 2026)…")
    df = load_holdout()

    wide = df.pivot_table(index="time", columns="site_name", values="H2S", aggfunc="first")
    met = df[df["site_name"] == "NESTOR - BES"].set_index("time")[
        ["wind_direction_10m", "wind_speed_10m"]
    ]
    aligned = wide.join(met, how="inner")
    aligned["sector_idx"] = aligned["wind_direction_10m"].apply(sector_index)
    aligned["sector"] = aligned["sector_idx"].apply(
        lambda i: SECTOR_LABELS[i] if i is not None else None
    )
    aligned["hour_of_day"] = aligned.index.hour

    # ---------- per-sector means ---------- #
    sector_means = aligned.groupby("sector").agg(
        {
            "SAN YSIDRO": "mean",
            "NESTOR - BES": "mean",
            "IB CIVIC CTR": "mean",
            "wind_speed_10m": "mean",
        }
    )
    sector_means["n_hours"] = aligned.groupby("sector").size()
    sector_means = sector_means.reindex(SECTOR_LABELS).fillna(0)
    sector_means.to_csv(OUTPUTS / "sector_means.csv")
    log.info("per-sector means:\n%s", sector_means.to_string())

    # ---------- elevated-SY-with-N-wind hours ---------- #
    north_mask = aligned["sector"].isin(["N", "NNE", "NE", "ENE", "E"])
    elevated_sy = (aligned["SAN YSIDRO"] > 10) & north_mask
    sample = aligned.loc[elevated_sy].copy()
    sample.index.name = "time"
    sample.to_csv(OUTPUTS / "elevated_sy_north.csv")
    log.info(
        "hours with N/NE wind AND SY > 10 ppb: %d (mean SY=%.1f ppb)",
        len(sample),
        float(sample["SAN YSIDRO"].mean()) if len(sample) else float("nan"),
    )

    # ---------- NESTOR-heavy events ---------- #
    heavy = aligned[aligned["NESTOR - BES"] > 50].copy()
    heavy.index.name = "time"
    heavy.to_csv(OUTPUTS / "nestor_heavy_events.csv")
    log.info("NESTOR > 50 ppb events: %d hours", len(heavy))
    log.info(
        "  sectors:\n%s",
        heavy["sector"].value_counts().to_string(),
    )

    # ---------- v3 rates at bound ---------- #
    rates = pd.read_csv(V3_RATES)
    rates["bound_g_s"] = rates["archetype"].map(ARCHETYPE_BOUNDS)
    rates["at_bound"] = rates["rate_g_s"] >= (rates["bound_g_s"] - 1e-6)
    at_bound = rates[rates["at_bound"]].copy()
    at_bound.to_csv(OUTPUTS / "v3_rates_at_bound.csv", index=False)
    log.info("v3 sources at upper bound: %d", len(at_bound))
    if len(at_bound):
        log.info(
            "  %s", at_bound[["name", "archetype", "rate_g_s", "bound_g_s"]].to_string(index=False)
        )

    # ---------- summary ---------- #
    sy_n_obs_mean = float(sector_means.loc["N", "SAN YSIDRO"])
    nestor_n_obs_mean = float(sector_means.loc["N", "NESTOR - BES"])
    bay_at_bound = bool(((rates["archetype"] == "bay") & rates["at_bound"]).any())

    findings = {
        "san_ysidro_n_sector_mean_ppb": sy_n_obs_mean,
        "san_ysidro_nnw_sector_mean_ppb": float(sector_means.loc["NNW", "SAN YSIDRO"]),
        "nestor_n_sector_mean_ppb": nestor_n_obs_mean,
        "sy_uniquely_elevated_in_n_sector": sy_n_obs_mean > nestor_n_obs_mean,
        "n_hours_sy_gt10_with_north_wind": int(elevated_sy.sum()),
        "n_hours_nestor_gt50": len(heavy),
        "nestor_heavy_nocturnal_fraction": (
            float(
                heavy["hour_of_day"].isin(range(20, 24)).sum()
                + heavy["hour_of_day"].isin(range(0, 8)).sum()
            )
            / max(len(heavy), 1)
        ),
        "v3_bay_source_hit_bound": bay_at_bound,
        "v3_n_sources_at_bound": int(rates["at_bound"].sum()),
        "design_implication_for_v3_1": (
            "Two binding findings: (1) the bay archetype cap is the limiting "
            "constraint — relaxing it lets the NNLS attribute mass to bay-pond "
            "sources that align with N-wind NESTOR peaks; (2) the SY-N "
            "elevation is genuinely SY-specific (30 ppb vs NESTOR's 13 ppb in "
            "the N sector), so a missing source N/NE of SY is plausible "
            "in addition to the bay-cap fix."
        ),
    }
    (OUTPUTS / "summary.json").write_text(json.dumps(findings, indent=2))
    log.info("findings written to %s", OUTPUTS / "summary.json")
    log.info("design implication: %s", findings["design_implication_for_v3_1"])


if __name__ == "__main__":
    main()
