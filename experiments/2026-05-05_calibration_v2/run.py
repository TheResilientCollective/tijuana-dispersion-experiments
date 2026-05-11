"""
Calibration experiment v2 — Mar 13-15, 2026.

Compared to demo_run.py:
  - Adds 12 distributed channel sources between Stewart's and the beach outlet
  - Adds 9 estuary/bay grid sources covering the western terminus
  - Uses run_inversion_bounded with archetype caps and prior shrinkage
  - Computes wind-conditional residuals to diagnose remaining errors
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/dispersion_service")

from tijuana_dispersion import (
    ForwardRunRequest,
    MetCondition,
    MetSpec,
    Receptor,
    ReceptorSpec,
    SourceSpec,
    distributed_area_sources,
    distributed_channel_sources,
    run_forward,
    run_inversion_bounded,
    wind_conditional_residuals,
)

DATA_PATH = "/mnt/project/modeldata_h2s_nofill.csv"
OUT_DIR = Path("/home/claude/calibration_v2_output")
OUT_DIR.mkdir(exist_ok=True)

WINDOW_START = "2026-03-13"
WINDOW_END = "2026-03-16"

RECEPTORS = [
    ReceptorSpec(name="SAN YSIDRO", lat=32.552794, lon=-117.047286),
    ReceptorSpec(name="NESTOR - BES", lat=32.567097, lon=-117.090656),
    ReceptorSpec(name="IB CIVIC CTR", lat=32.576139, lon=-117.115361),
]


# Tier 1: 17 named sources (unchanged from demo)
NAMED_SOURCES = [
    SourceSpec(
        name="Stewart's Drain",
        lat=32.54064,
        lon=-117.05801,
        archetype="drain",
        emission_rate_g_s=0.5,
        height_m=1.0,
    ),
    SourceSpec(
        name="Smuggler's Gulch",
        lat=32.5377,
        lon=-117.08623,
        archetype="drain",
        emission_rate_g_s=0.5,
        height_m=1.0,
    ),
    SourceSpec(
        name="Hollister St PS",
        lat=32.5476,
        lon=-117.088374,
        archetype="drain",
        emission_rate_g_s=0.3,
        height_m=1.0,
    ),
    SourceSpec(
        name="Goat Canyon",
        lat=32.5369,
        lon=-117.09916,
        archetype="drain",
        emission_rate_g_s=0.3,
        height_m=1.0,
    ),
    SourceSpec(
        name="Goat Canyon PS",
        lat=32.543476,
        lon=-117.108026,
        archetype="drain",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Del Sol Canyon",
        lat=32.5393,
        lon=-117.06885,
        archetype="drain",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Silva Drain",
        lat=32.539743,
        lon=-117.064269,
        archetype="drain",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Saturn Blvd Bridge",
        lat=32.559383,
        lon=-117.092992,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Hollister St Bridge N",
        lat=32.554177,
        lon=-117.084135,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Hollister St Bridge S",
        lat=32.551466,
        lon=-117.084021,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Dairy Mart Bridge",
        lat=32.548531,
        lon=-117.064293,
        archetype="channel",
        emission_rate_g_s=0.1,
        height_m=1.0,
    ),
    SourceSpec(
        name="Oneonta Slough Near IB",
        lat=32.570082,
        lon=-117.126724,
        archetype="estuary",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Tijuana River Beach Outlet",
        lat=32.556206,
        lon=-117.126178,
        archetype="estuary",
        emission_rate_g_s=0.3,
        height_m=1.0,
    ),
    SourceSpec(
        name="Tijuana River Crossing CDLP W",
        lat=32.542103,
        lon=-117.054117,
        archetype="channel",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="Tijuana River Crossing CDLP E",
        lat=32.542166,
        lon=-117.050325,
        archetype="channel",
        emission_rate_g_s=0.2,
        height_m=1.0,
    ),
    SourceSpec(
        name="San Diego Bay ponds Otay River Outlet",
        lat=32.594557,
        lon=-117.113542,
        archetype="bay",
        emission_rate_g_s=0.05,
        height_m=1.0,
    ),
    SourceSpec(
        name="San Diego Bay Ponds near Fruitdale",
        lat=32.595305,
        lon=-117.091869,
        archetype="bay",
        emission_rate_g_s=0.05,
        height_m=1.0,
    ),
]


def build_full_source_field():
    """Tier 1 (named) + Tier 2 (channel) + Tier 3 (estuary/bay grid)."""
    # Channel: 12 sources from Stewart's to just east of beach outlet
    channel = distributed_channel_sources(
        start_lat=32.54064,
        start_lon=-117.05801,  # Stewart's
        end_lat=32.555,
        end_lon=-117.115,  # near beach outlet
        n_sources=12,
        archetype="channel",
        seed_rate_g_s=0.1,
        name_prefix="channel",
    )
    # Estuary: 3x3 grid covering Tijuana estuary mudflats
    estuary = distributed_area_sources(
        bounding_box=(32.555, -117.135, 32.580, -117.115),
        nx=3,
        ny=3,
        archetype="estuary",
        seed_rate_g_s=0.1,
        name_prefix="estuary",
    )
    return NAMED_SOURCES + channel + estuary


# ---------- helpers (same as demo_run.py) ---------- #


def load_window():
    df = pd.read_csv(DATA_PATH, parse_dates=["time"])
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    mask = (df["time"] >= WINDOW_START) & (df["time"] < WINDOW_END)
    df = df[mask].copy()
    df["hour"] = df["time"].dt.floor("h")
    cols = [
        "hour",
        "site_name",
        "H2S",
        "wind_speed_10m",
        "wind_direction_10m",
        "temperature_2m",
        "cloud_cover",
        "is_night",
    ]
    return df[cols].groupby(["hour", "site_name"]).mean(numeric_only=True).reset_index()


def build_met_series(df_window):
    nestor = df_window[df_window["site_name"] == "NESTOR - BES"].sort_values("hour")
    out = []
    for _, row in nestor.iterrows():
        if pd.isna(row["wind_speed_10m"]) or pd.isna(row["wind_direction_10m"]):
            continue
        out.append(
            MetSpec(
                timestamp=row["hour"].isoformat(),
                wind_speed_ms=float(row["wind_speed_10m"]),
                wind_direction_deg=float(row["wind_direction_10m"]),
                temperature_c=float(row["temperature_2m"]),
                cloud_cover_frac=(
                    float(row["cloud_cover"]) / 100.0 if not pd.isna(row["cloud_cover"]) else 0.5
                ),
                is_night=bool(row["is_night"] >= 0.5) if not pd.isna(row["is_night"]) else False,
            )
        )
    return out


def build_obs_array(df_window, hours, names):
    obs = np.full((len(hours), len(names)), np.nan)
    for h_idx, h in enumerate(hours):
        for r_idx, rname in enumerate(names):
            row = df_window[(df_window["hour"] == h) & (df_window["site_name"] == rname)]
            if len(row) and not pd.isna(row.iloc[0]["H2S"]):
                obs[h_idx, r_idx] = float(row.iloc[0]["H2S"])
    return obs


def metspec_to_metcondition(m: MetSpec) -> MetCondition:
    return MetCondition(
        timestamp=m.timestamp,
        wind_speed_ms=m.wind_speed_ms,
        wind_direction_deg=m.wind_direction_deg,
        temperature_c=m.temperature_c,
        cloud_cover_frac=m.cloud_cover_frac,
        is_night=m.is_night,
    )


def receptorspec_to_receptor(r: ReceptorSpec) -> Receptor:
    return Receptor(name=r.name, lat=r.lat, lon=r.lon, height_m=r.height_m)


def main():
    print("=== Calibration Experiment v2 — Mar 13-15, 2026 ===\n")

    df = load_window()
    met_specs = build_met_series(df)
    hours = pd.to_datetime([m.timestamp for m in met_specs])
    receptor_names = [r.name for r in RECEPTORS]
    obs = build_obs_array(df, hours, receptor_names)

    sources = build_full_source_field()
    print(f"Source field: {len(sources)} total")
    arch_counts = pd.Series([s.archetype for s in sources]).value_counts()
    for arch, n in arch_counts.items():
        print(f"  {arch:<10} {n}")
    print(
        f"\nWindow: {len(hours)}h × {len(RECEPTORS)} receptors = " f"{(~np.isnan(obs)).sum()} obs\n"
    )

    # ---------- bounded inversion ---------- #
    print("--- Bounded NNLS with archetype priors ---")
    receptors_core = [receptorspec_to_receptor(r) for r in RECEPTORS]
    met_core = [metspec_to_metcondition(m) for m in met_specs]

    inv = run_inversion_bounded(
        sources=sources,
        receptors=receptors_core,
        met=met_core,
        observations=obs,
        prior_lambda=0.5,
        smoothness_lambda=0.3,
    )
    print(f"  residual RMS: {inv.residual_rms_ppb:.2f} ppb")
    print(f"  sources at upper bound: {inv.n_at_bound} / {len(sources)}")
    print(f"  iterations: {inv.diagnostics['n_iter']}")
    print()

    # Show top-10 fitted rates
    rate_df = pd.DataFrame(
        {
            "name": inv.source_names,
            "archetype": inv.archetypes,
            "rate_g_s": inv.fitted_rates_g_s,
            "bound_g_s": inv.upper_bounds_g_s,
        }
    )
    print("Top fitted rates:")
    print(rate_df.nlargest(15, "rate_g_s").to_string(index=False))
    print()
    print("Total emission by archetype (g/s):")
    print(rate_df.groupby("archetype")["rate_g_s"].agg(["sum", "mean", "count"]))
    print()

    # ---------- forward verification with fitted rates ---------- #
    fitted_sources = [
        SourceSpec(
            name=s.name,
            lat=s.lat,
            lon=s.lon,
            archetype=s.archetype,
            emission_rate_g_s=r,
            height_m=s.height_m,
        )
        for s, r in zip(sources, inv.fitted_rates_g_s, strict=False)
    ]
    fwd = run_forward(
        ForwardRunRequest(
            sources=fitted_sources,
            receptors=RECEPTORS,
            meteorology=met_specs,
            units="ppb",
            notes="calibration v2 fitted rates",
        )
    )
    pred = np.array(fwd.concentrations)

    print("Per-station fit:")
    for r_idx, rname in enumerate(receptor_names):
        valid = ~np.isnan(obs[:, r_idx])
        if valid.sum() < 5:
            corr = float("nan")
        else:
            corr = np.corrcoef(pred[valid, r_idx], obs[valid, r_idx])[0, 1]
        print(
            f"  {rname:<14}  pred_max={np.nanmax(pred[:,r_idx]):7.1f}  "
            f"obs_max={np.nanmax(obs[:,r_idx]):7.1f}  r={corr:.2f}"
        )
    print()

    # ---------- wind-conditional residuals ---------- #
    print("--- Wind-conditional residuals (top biased sectors) ---")
    wind_df = wind_conditional_residuals(pred, obs, met_core, receptor_names)
    # Show sectors with biggest absolute mean residual per station
    for rname in receptor_names:
        sub = wind_df[(wind_df["receptor"] == rname) & (wind_df["n_hours"] >= 3)]
        if len(sub) == 0:
            continue
        sub = sub.assign(abs_resid=sub["resid_mean"].abs()).nlargest(4, "abs_resid")
        print(f"\n  {rname}")
        print(
            sub[["wind_sector", "n_hours", "obs_mean", "pred_mean", "resid_mean"]].to_string(
                index=False, float_format=lambda x: f"{x:6.1f}"
            )
        )
    print()

    # ---------- save artifacts ---------- #
    rate_df.to_csv(OUT_DIR / "fitted_rates.csv", index=False)
    wind_df.to_csv(OUT_DIR / "wind_residuals.csv", index=False)

    # Time series for plotting
    ts_df = pd.DataFrame(
        {
            "hour": hours,
            **{f"obs_{r}": obs[:, i] for i, r in enumerate(receptor_names)},
            **{f"pred_{r}": pred[:, i] for i, r in enumerate(receptor_names)},
        }
    )
    ts_df.to_csv(OUT_DIR / "timeseries.csv", index=False)

    summary = {
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "n_sources": len(sources),
        "n_named": 17,
        "n_channel": 12,
        "n_estuary_grid": 9,
        "n_observations": int((~np.isnan(obs)).sum()),
        "residual_rms_ppb": inv.residual_rms_ppb,
        "n_at_bound": inv.n_at_bound,
        "max_predicted": float(np.nanmax(pred)),
        "max_observed": float(np.nanmax(obs)),
        "per_station_correlation": {
            rname: float(
                np.corrcoef(
                    pred[~np.isnan(obs[:, r_idx]), r_idx],
                    obs[~np.isnan(obs[:, r_idx]), r_idx],
                )[0, 1]
            )
            if (~np.isnan(obs[:, r_idx])).sum() >= 5
            else None
            for r_idx, rname in enumerate(receptor_names)
        },
        "total_emission_by_archetype_g_s": (
            rate_df.groupby("archetype")["rate_g_s"].sum().to_dict()
        ),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nArtifacts saved to {OUT_DIR}")
    return summary


if __name__ == "__main__":
    main()
