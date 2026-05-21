"""Demo run: forward model + inversion for March 13-15, 2026 window
covering the documented Stewart's Drain spill event.

This is a 'rough run' to prove the service pipeline works end-to-end
on real data and to give a baseline before formal calibration.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/dispersion_service")

from tijuana_dispersion import (
    ForwardRunRequest,
    InversionRequest,
    MetSpec,
    ReceptorSpec,
    SourceSpec,
    run_forward,
    run_inversion,
)

# ---------------- Configuration ---------------- #
DATA_PATH = "/mnt/project/modeldata_h2s_nofill.csv"
OUT_DIR = Path("/home/claude/demo_output")
OUT_DIR.mkdir(exist_ok=True)

# Demo window — covers Stewart's Drain event of Mar 14-15
WINDOW_START = "2026-03-13"
WINDOW_END = "2026-03-16"

# Fixed receptors (from sensors.json)
RECEPTORS = [
    ReceptorSpec(name="SAN YSIDRO", lat=32.552794, lon=-117.047286),
    ReceptorSpec(name="NESTOR - BES", lat=32.567097, lon=-117.090656),
    ReceptorSpec(name="IB CIVIC CTR", lat=32.576139, lon=-117.115361),
]

# Tier-1 sources (from emission_sources.json) — start with seed rates
# differentiated by archetype prior. The 17 named sources.
SEED_SOURCES_RAW = [
    # name, lat, lon, archetype, seed_rate_g_s
    ("Stewart's Drain", 32.54064, -117.05801, "drain", 0.5),
    ("Smuggler's Gulch", 32.5377, -117.08623, "drain", 0.5),
    ("Hollister St PS", 32.5476, -117.088374, "drain", 0.3),
    ("Goat Canyon", 32.5369, -117.09916, "drain", 0.3),
    ("Goat Canyon PS", 32.543476, -117.108026, "drain", 0.2),
    ("Del Sol Canyon", 32.5393, -117.06885, "drain", 0.2),
    ("Silva Drain", 32.539743, -117.064269, "drain", 0.2),
    ("Saturn Blvd Bridge", 32.559383, -117.092992, "channel", 0.1),
    ("Hollister St Bridge N", 32.554177, -117.084135, "channel", 0.1),
    ("Hollister St Bridge S", 32.551466, -117.084021, "channel", 0.1),
    ("Dairy Mart Bridge", 32.548531, -117.064293, "channel", 0.1),
    ("Oneonta Slough Near IB", 32.570082, -117.126724, "estuary", 0.2),
    ("Tijuana River Beach Outlet", 32.556206, -117.126178, "estuary", 0.3),
    ("Tijuana River Crossing CDLP W", 32.542103, -117.054117, "channel", 0.2),
    ("Tijuana River Crossing CDLP E", 32.542166, -117.050325, "channel", 0.2),
    ("San Diego Bay ponds Otay River Outlet", 32.594557, -117.113542, "bay", 0.05),
    ("San Diego Bay Ponds near Fruitdale", 32.595305, -117.091869, "bay", 0.05),
]


def build_sources(rates=None):
    rates_used = rates if rates is not None else [s[4] for s in SEED_SOURCES_RAW]
    return [
        SourceSpec(
            name=name,
            lat=lat,
            lon=lon,
            archetype=arche,
            emission_rate_g_s=rate,
            height_m=1.0,
        )
        for (name, lat, lon, arche, _seed), rate in zip(SEED_SOURCES_RAW, rates_used, strict=False)
    ]


def load_window():
    """Load demo window, hourly, all three sites pivoted."""
    df = pd.read_csv(DATA_PATH, parse_dates=["time"])
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    mask = (df["time"] >= WINDOW_START) & (df["time"] < WINDOW_END)
    df = df[mask].copy()
    # Resample to hourly, mean
    df["hour"] = df["time"].dt.floor("h")
    cols_keep = [
        "hour",
        "site_name",
        "H2S",
        "wind_speed_10m",
        "wind_direction_10m",
        "temperature_2m",
        "cloud_cover",
        "is_night",
    ]
    df = df[cols_keep].groupby(["hour", "site_name"]).mean(numeric_only=True).reset_index()
    return df


def build_met_series(df_window):
    """One met record per hour (use NESTOR row's met as canonical)."""
    nestor = df_window[df_window["site_name"] == "NESTOR - BES"].sort_values("hour")
    met_list = []
    for _, row in nestor.iterrows():
        if pd.isna(row["wind_speed_10m"]) or pd.isna(row["wind_direction_10m"]):
            continue
        met_list.append(
            MetSpec(
                timestamp=row["hour"].isoformat(),
                wind_speed_ms=float(row["wind_speed_10m"]),
                wind_direction_deg=float(row["wind_direction_10m"]),
                temperature_c=float(row["temperature_2m"]),
                cloud_cover_frac=float(row["cloud_cover"]) / 100.0
                if not pd.isna(row["cloud_cover"])
                else 0.5,
                is_night=bool(row["is_night"] >= 0.5) if not pd.isna(row["is_night"]) else False,
            ),
        )
    return met_list


def build_obs_array(df_window, hours, receptor_names):
    """Build (n_hours, n_receptors) observation matrix in same order as receptors."""
    obs = np.full((len(hours), len(receptor_names)), np.nan)
    for h_idx, h in enumerate(hours):
        for r_idx, rname in enumerate(receptor_names):
            row = df_window[(df_window["hour"] == h) & (df_window["site_name"] == rname)]
            if len(row) and not pd.isna(row.iloc[0]["H2S"]):
                obs[h_idx, r_idx] = float(row.iloc[0]["H2S"])
    return obs


def main():
    print("=== Tijuana Dispersion Service Demo ===")
    print(f"Window: {WINDOW_START} to {WINDOW_END}\n")

    df = load_window()
    print(f"Loaded {len(df)} site-hours of data")

    met_series = build_met_series(df)
    print(f"Built met series: {len(met_series)} hours")

    hours = pd.to_datetime([m.timestamp for m in met_series])
    receptor_names = [r.name for r in RECEPTORS]
    obs = build_obs_array(df, hours, receptor_names)

    n_obs = (~np.isnan(obs)).sum()
    print(
        f"Observations: {n_obs} non-NaN cells across {len(hours)}h × {len(RECEPTORS)} receptors\n",
    )

    # ---------- 1. Forward run with seed rates ---------- #
    print("--- Forward run with seed emission rates ---")
    sources = build_sources()
    fwd_req = ForwardRunRequest(
        sources=sources,
        receptors=RECEPTORS,
        meteorology=met_series,
        units="ppb",
        return_per_source=False,
        notes="seed rates, Mar 13-15 demo",
    )
    fwd_result = run_forward(fwd_req)
    pred_seed = np.array(fwd_result.concentrations)

    print(f"  runtime: {fwd_result.runtime_ms} ms")
    print(f"  max predicted: {fwd_result.summary['max_concentration']:.1f} ppb")
    print(f"  max observed:  {np.nanmax(obs):.1f} ppb")
    for r_idx, rname in enumerate(receptor_names):
        pred_max = np.nanmax(pred_seed[:, r_idx])
        obs_max = np.nanmax(obs[:, r_idx])
        print(f"    {rname:<14}  pred_max={pred_max:7.1f}  obs_max={obs_max:7.1f}")
    print()

    # ---------- 2. Inversion to fit emission rates ---------- #
    print("--- NNLS inversion to fit emission rates ---")
    inv_req = InversionRequest(
        sources=sources,
        receptors=RECEPTORS,
        meteorology=met_series,
        observations=obs.tolist(),
        l1_lambda=0.5,  # mild shrinkage
    )
    inv_result = run_inversion(inv_req)
    print(f"  residual RMS: {inv_result.residual_rms:.2f} ppb")
    print(f"  observations used: {inv_result.fit_diagnostics['n_observations']}")
    print()
    print("  fitted rates (g/s):")
    for name, rate in zip(inv_result.source_names, inv_result.fitted_rates_g_s, strict=False):
        bar = "█" * int(min(rate * 5, 60))
        print(f"    {name:<42}  {rate:7.3f}  {bar}")
    print()

    # ---------- 3. Forward run with fitted rates ---------- #
    print("--- Forward run with fitted rates (verification) ---")
    fitted_sources = build_sources(rates=inv_result.fitted_rates_g_s)
    fwd_req2 = ForwardRunRequest(
        sources=fitted_sources,
        receptors=RECEPTORS,
        meteorology=met_series,
        units="ppb",
        return_per_source=False,
        notes="fitted rates",
    )
    fwd2 = run_forward(fwd_req2)
    pred_fit = np.array(fwd2.concentrations)
    for r_idx, rname in enumerate(receptor_names):
        pred_max = np.nanmax(pred_fit[:, r_idx])
        obs_max = np.nanmax(obs[:, r_idx])
        # Per-station correlation
        valid = ~np.isnan(obs[:, r_idx])
        if valid.sum() > 5:
            corr = np.corrcoef(pred_fit[valid, r_idx], obs[valid, r_idx])[0, 1]
        else:
            corr = float("nan")
        print(f"    {rname:<14}  pred_max={pred_max:7.1f}  obs_max={obs_max:7.1f}  r={corr:.2f}")

    # ---------- 4. Save artifacts ---------- #
    artifacts = {
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "n_hours": len(hours),
        "n_observations": int(n_obs),
        "seed_rates_g_s": [s.emission_rate_g_s for s in sources],
        "fitted_rates_g_s": inv_result.fitted_rates_g_s,
        "source_names": inv_result.source_names,
        "residual_rms_ppb": inv_result.residual_rms,
        "max_predicted_seed": float(fwd_result.summary["max_concentration"]),
        "max_predicted_fitted": float(fwd2.summary["max_concentration"]),
        "max_observed": float(np.nanmax(obs)),
    }
    (OUT_DIR / "demo_artifacts.json").write_text(json.dumps(artifacts, indent=2))
    print(f"\nArtifacts saved to {OUT_DIR / 'demo_artifacts.json'}")

    # Save time series
    ts_df = pd.DataFrame(
        {
            "hour": hours,
            **{f"obs_{r}": obs[:, i] for i, r in enumerate(receptor_names)},
            **{f"pred_seed_{r}": pred_seed[:, i] for i, r in enumerate(receptor_names)},
            **{f"pred_fit_{r}": pred_fit[:, i] for i, r in enumerate(receptor_names)},
        },
    )
    ts_df.to_csv(OUT_DIR / "demo_timeseries.csv", index=False)
    print(f"Time series saved to {OUT_DIR / 'demo_timeseries.csv'}")


if __name__ == "__main__":
    main()
