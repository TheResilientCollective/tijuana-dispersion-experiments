"""
Sensitivity analysis on the emissions model parameters.

A miniature illustration of the kind of compute-rich calibration NRP
would enable at scale. Latin Hypercube samples 11 emission parameters
across physically reasonable ranges, computes predicted concentrations
for each sample on the Mar 13-15 window, and reports sensitivity via
Pearson correlation between each parameter and each fit metric.

At full scale on NRP this is ~10,000 samples × HYSPLIT in the loop,
~CPU-hour scale. Here it's 200 samples × Gaussian plume = ~30 seconds.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/claude/dispersion_service")

from tijuana_dispersion import (
    EmissionDrivers,
    EmissionParameters,
    EmissionsModel,
    MetCondition,
    Receptor,
    ReceptorSpec,
    Source,
    SourceSpecLocation,
    forward_run,
)

OUT = Path("/home/claude/sensitivity_output")
OUT.mkdir(exist_ok=True)
WINDOW = ("2026-03-13", "2026-03-16")

RECEPTORS = [
    ReceptorSpec(name="SAN YSIDRO", lat=32.552794, lon=-117.047286),
    ReceptorSpec(name="NESTOR - BES", lat=32.567097, lon=-117.090656),
    ReceptorSpec(name="IB CIVIC CTR", lat=32.576139, lon=-117.115361),
]

LOCATIONS = [
    SourceSpecLocation("Stewart's Drain", 32.54064, -117.05801, "drain"),
    SourceSpecLocation("Smuggler's Gulch", 32.5377, -117.08623, "drain"),
    SourceSpecLocation("Hollister St PS", 32.5476, -117.088374, "drain"),
    SourceSpecLocation("Goat Canyon", 32.5369, -117.09916, "drain"),
    SourceSpecLocation("Goat Canyon PS", 32.543476, -117.108026, "drain"),
    SourceSpecLocation("Del Sol Canyon", 32.5393, -117.06885, "drain"),
    SourceSpecLocation("Silva Drain", 32.539743, -117.064269, "drain"),
    SourceSpecLocation("Saturn Blvd Bridge", 32.559383, -117.092992, "channel"),
    SourceSpecLocation("Hollister St Bridge N", 32.554177, -117.084135, "channel"),
    SourceSpecLocation("Hollister St Bridge S", 32.551466, -117.084021, "channel"),
    SourceSpecLocation("Dairy Mart Bridge", 32.548531, -117.064293, "channel"),
    SourceSpecLocation("Oneonta Slough", 32.570082, -117.126724, "estuary"),
    SourceSpecLocation("Beach Outlet", 32.556206, -117.126178, "estuary"),
    SourceSpecLocation("CDLP W", 32.542103, -117.054117, "channel"),
    SourceSpecLocation("CDLP E", 32.542166, -117.050325, "channel"),
    SourceSpecLocation("Otay Pond", 32.594557, -117.113542, "bay"),
    SourceSpecLocation("Fruitdale Pond", 32.595305, -117.091869, "bay"),
]

# Parameter ranges for the LHS sample. Physically motivated bounds.
PARAM_RANGES = {
    "baseline_scale": (1.0, 200.0),  # global multiplier on baselines
    "Q10": (1.5, 3.5),
    "T_ref_c": (10.0, 30.0),
    "substrate_alpha": (0.0, 0.5),
    "substrate_threshold": (10.0, 40.0),
    "diel_amplitude": (1.0, 5.0),
    "diel_phase_hours": (0.0, 12.0),
    "f_arch_drain": (0.5, 5.0),
    "f_arch_channel": (0.1, 2.0),
    "f_arch_estuary": (0.1, 3.0),
    "f_arch_bay": (0.0, 0.5),
}


def latin_hypercube(n_samples: int, n_dims: int, seed: int = 42) -> np.ndarray:
    """Standard LHS in [0,1]^d."""
    rng = np.random.default_rng(seed)
    cuts = np.linspace(0, 1, n_samples + 1)
    u = rng.uniform(size=(n_samples, n_dims))
    rdpoints = cuts[:n_samples, None] + u * (cuts[1:, None] - cuts[:n_samples, None])
    H = np.zeros_like(rdpoints)
    for j in range(n_dims):
        H[:, j] = rng.permutation(rdpoints[:, j])
    return H


def load_window():
    df = pd.read_csv("/mnt/project/modeldata_h2s_nofill.csv", parse_dates=["time"])
    df["time"] = pd.to_datetime(df["time"], utc=True).dt.tz_convert("America/Los_Angeles")
    df = df[(df["time"] >= WINDOW[0]) & (df["time"] < WINDOW[1])].copy()
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
        "sbiwtp_flow_mgd",
        "sbiwtp_deficit",
        "tide_height",
    ]
    return df[cols].groupby(["hour", "site_name"]).mean(numeric_only=True).reset_index()


def make_drivers_and_met(df_window):
    nestor = df_window[df_window["site_name"] == "NESTOR - BES"].sort_values("hour")
    drivers = []
    met = []
    for _, row in nestor.iterrows():
        if pd.isna(row["wind_speed_10m"]) or pd.isna(row["wind_direction_10m"]):
            continue
        drivers.append(
            EmissionDrivers(
                timestamp=row["hour"].isoformat(),
                temperature_c=float(row["temperature_2m"]),
                wind_speed_10m_ms=float(row["wind_speed_10m"]),
                sbiwtp_flow_mgd=float(row["sbiwtp_flow_mgd"]),
                sbiwtp_deficit=float(row["sbiwtp_deficit"])
                if not pd.isna(row["sbiwtp_deficit"])
                else 0.0,
                tide_height_m=float(row["tide_height"]) if not pd.isna(row["tide_height"]) else 0.0,
                is_night=bool(row["is_night"] >= 0.5),
            )
        )
        met.append(
            MetCondition(
                timestamp=row["hour"].isoformat(),
                wind_speed_ms=float(row["wind_speed_10m"]),
                wind_direction_deg=float(row["wind_direction_10m"]),
                temperature_c=float(row["temperature_2m"]),
                cloud_cover_frac=float(row["cloud_cover"]) / 100.0
                if not pd.isna(row["cloud_cover"])
                else 0.5,
                is_night=bool(row["is_night"] >= 0.5),
            )
        )
    return drivers, met


def build_obs(df_window, hours, names):
    obs = np.full((len(hours), len(names)), np.nan)
    for h_idx, h in enumerate(hours):
        for r_idx, n in enumerate(names):
            row = df_window[(df_window["hour"] == h) & (df_window["site_name"] == n)]
            if len(row) and not pd.isna(row.iloc[0]["H2S"]):
                obs[h_idx, r_idx] = float(row.iloc[0]["H2S"])
    return obs


def evaluate_one(sample_dict, drivers, met, obs, receptor_names):
    """Run one parameter set, return summary metrics per receptor."""
    # Build EmissionParameters from the sample
    params = EmissionParameters(
        Q10=sample_dict["Q10"],
        T_ref_c=sample_dict["T_ref_c"],
        substrate_alpha=sample_dict["substrate_alpha"],
        substrate_threshold_mgd=sample_dict["substrate_threshold"],
        diel_amplitude=sample_dict["diel_amplitude"],
        diel_phase_hours=sample_dict["diel_phase_hours"],
        f_arch={
            "drain": sample_dict["f_arch_drain"],
            "channel": sample_dict["f_arch_channel"],
            "estuary": sample_dict["f_arch_estuary"],
            "bay": sample_dict["f_arch_bay"],
            "spill": 1.0,
        },
        # All sources get baseline of 1 g/s × global scale
        baselines_g_s={loc.name: sample_dict["baseline_scale"] for loc in LOCATIONS},
    )
    em = EmissionsModel(params)

    # Compute concentrations: for each timestep, build sources and forward-run
    receptors_core = [
        Receptor(name=r.name, lat=r.lat, lon=r.lon, height_m=r.height_m) for r in RECEPTORS
    ]
    pred = np.zeros((len(drivers), len(receptors_core)))
    for t_idx, drv in enumerate(drivers):
        sources = [
            Source(
                name=loc.name,
                lat=loc.lat,
                lon=loc.lon,
                emission_rate_g_s=em.emission_rate_g_s(loc, drv),
                height_m=loc.height_m,
                archetype=loc.archetype,
            )
            for loc in LOCATIONS
        ]
        pred[t_idx] = forward_run(sources, receptors_core, [met[t_idx]], units="ppb")[0]

    # Per-receptor metrics
    metrics = {}
    for r_idx, name in enumerate(receptor_names):
        valid = ~np.isnan(obs[:, r_idx])
        if valid.sum() < 5:
            continue
        o = obs[valid, r_idx]
        p = pred[valid, r_idx]
        metrics[name] = {
            "rms": float(np.sqrt(np.mean((o - p) ** 2))),
            "corr": float(np.corrcoef(o, p)[0, 1]) if p.std() > 0 else 0.0,
            "max_pred": float(p.max()),
            "max_obs": float(o.max()),
            "peak_ratio": float(p.max() / (o.max() + 1e-6)),
        }
    return metrics


def main():
    print("=== Emissions Model Sensitivity Analysis ===\n")
    df = load_window()
    drivers, met = make_drivers_and_met(df)
    hours = pd.to_datetime([d.timestamp for d in drivers])
    receptor_names = [r.name for r in RECEPTORS]
    obs = build_obs(df, hours, receptor_names)
    print(f"Window: {len(drivers)} hours, {(~np.isnan(obs)).sum()} obs\n")

    # LHS sample
    n_samples = 200
    param_names = list(PARAM_RANGES.keys())
    H = latin_hypercube(n_samples, len(param_names), seed=42)
    samples = []
    for i in range(n_samples):
        sd = {}
        for j, pname in enumerate(param_names):
            lo, hi = PARAM_RANGES[pname]
            sd[pname] = lo + H[i, j] * (hi - lo)
        samples.append(sd)
    print(f"Drew {n_samples} LHS samples across {len(param_names)} parameters\n")

    # Evaluate each sample
    import time

    t0 = time.time()
    rows = []
    for i, s in enumerate(samples):
        m = evaluate_one(s, drivers, met, obs, receptor_names)
        row = dict(s)
        row["sample_id"] = i
        for rname in receptor_names:
            if rname in m:
                row[f"rms_{rname}"] = m[rname]["rms"]
                row[f"corr_{rname}"] = m[rname]["corr"]
                row[f"peak_ratio_{rname}"] = m[rname]["peak_ratio"]
        rows.append(row)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{n_samples}  ({(time.time()-t0)/(i+1)*1000:.0f} ms/run)")
    elapsed = time.time() - t0
    print(f"\nTotal: {elapsed:.1f} s  ({elapsed/n_samples*1000:.0f} ms/run)\n")

    df_results = pd.DataFrame(rows)
    df_results.to_csv(OUT / "sensitivity_samples.csv", index=False)

    # Sensitivity = Pearson correlation between each parameter and each metric
    sens_rows = []
    metric_cols = [c for c in df_results.columns if c.startswith(("rms_", "corr_", "peak_ratio_"))]
    for pname in param_names:
        for mcol in metric_cols:
            valid = ~df_results[mcol].isna()
            if valid.sum() < 10:
                continue
            r = np.corrcoef(df_results.loc[valid, pname], df_results.loc[valid, mcol])[0, 1]
            sens_rows.append(
                {
                    "parameter": pname,
                    "metric": mcol,
                    "pearson_r": float(r),
                    "abs_r": abs(float(r)),
                }
            )
    sens = pd.DataFrame(sens_rows)
    sens.to_csv(OUT / "sensitivities.csv", index=False)

    # Find parameter set that best matches observations (lowest combined RMS)
    rms_cols = [c for c in df_results.columns if c.startswith("rms_")]
    df_results["combined_rms"] = df_results[rms_cols].mean(axis=1)
    best = df_results.nsmallest(5, "combined_rms")
    print("--- Top 5 parameter sets by combined RMS ---")
    print(
        best[
            [
                "sample_id",
                "combined_rms",
                "baseline_scale",
                "Q10",
                "f_arch_drain",
                "f_arch_estuary",
                "diel_amplitude",
                *rms_cols,
            ]
        ].to_string(index=False, float_format=lambda x: f"{x:7.2f}")
    )
    print()

    # Top sensitivities per metric type
    for kind in ["corr", "rms", "peak_ratio"]:
        print(f"--- Top 5 parameter sensitivities for {kind} (|Pearson r|) ---")
        sub = sens[sens["metric"].str.startswith(kind + "_")]
        for rname in receptor_names:
            top = sub[sub["metric"] == f"{kind}_{rname}"].nlargest(5, "abs_r")
            if len(top) == 0:
                continue
            print(f"  {rname}:")
            for _, row in top.iterrows():
                sign = "+" if row["pearson_r"] > 0 else "-"
                print(f"    {sign} {row['parameter']:<22} r = {row['pearson_r']:+.3f}")
        print()

    # Save best parameters for reuse
    best_dict = best.iloc[0][param_names].to_dict()
    (OUT / "best_parameters.json").write_text(
        json.dumps(
            {
                "parameters": best_dict,
                "combined_rms": float(best.iloc[0]["combined_rms"]),
                "per_receptor_corr": {r: float(best.iloc[0][f"corr_{r}"]) for r in receptor_names},
            },
            indent=2,
        )
    )
    print(f"Best parameters saved to {OUT/'best_parameters.json'}")
    print(f"Full sample results: {OUT/'sensitivity_samples.csv'}")
    print(f"Sensitivity table:   {OUT/'sensitivities.csv'}")


if __name__ == "__main__":
    main()
