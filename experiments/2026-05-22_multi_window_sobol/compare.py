"""Multi-window Sobol comparison — evaluates the H1-H6 predictions.

After `submit_sobol.py --windows-file windows.yaml` finishes and the
six archival snapshots land at ``s3://<bucket>/runs/<tag>/``, run:

    source nrp/.env
    uv run python experiments/2026-05-22_multi_window_sobol/compare.py

Outputs go under ``output/`` (gitignored):
    cross_window_st.csv   — long form (window, metric, parameter, S1, ST, …)
    per_window_top.csv    — top-5 by ST per (window, metric)
    predictions.json      — H1..H6 PASS / FAIL with the actual numbers
    summary.md            — human-readable digest for RESULTS.md

The predictions are *pre-registered* in README.md before the data
exists. This script evaluates them mechanically; it does not invent
new ones after seeing the indices.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import boto3
import pandas as pd

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from nrp.sobol import Window, load_windows  # noqa: E402

WINDOWS_YAML = HERE / "windows.yaml"
OUT = HERE / "output"

# These MUST match the submitter's defaults so the archive tags are
# discoverable. If you ran a different N/seed, pass --n-base-samples /
# --seed to override at the CLI.
DEFAULT_N = 8192
DEFAULT_SEED = 42

# Window classification for H4 (Q10 regime-conditional) and H6 (substrate
# seasonality). Anchored to the pre-registered partition in README.md.
WARM_WINDOWS = {"2025-09-01", "2026-04-04", "2026-05-10"}
COOL_WINDOWS = {"2025-12-20", "2026-02-08", "2026-03-13"}
DRY_SEASON_WINDOWS = {"2025-09-01", "2026-05-10"}
WET_SEASON_WINDOWS = {"2025-12-20", "2026-02-08"}

CORR_METRICS = (
    "corr__SAN YSIDRO",
    "corr__NESTOR - BES",
    "corr__IB CIVIC CTR",
)
MAGNITUDE_METRICS = (
    "rms__SAN YSIDRO",
    "rms__NESTOR - BES",
    "rms__IB CIVIC CTR",
    "peak_ratio__SAN YSIDRO",
    "peak_ratio__NESTOR - BES",
    "peak_ratio__IB CIVIC CTR",
)


# ---------- S3 ---------- #


def _s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_DEFAULT_REGION", "us-west-2"),
    )


def discover_archive_tag(
    s3: Any,
    bucket: str,
    window: Window,
    n_base_samples: int,
    seed: int,
) -> str | None:
    """Find the most recent archival tag for this window. Returns
    ``None`` if no archive exists yet (the user hasn't run that
    window)."""
    prefix = f"runs/{window.start}_{window.end}_N{n_base_samples}_seed{seed}_"
    paginator = s3.get_paginator("list_objects_v2")
    tags: set[str] = set()
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            parts = obj["Key"].split("/")
            if len(parts) >= 2:
                tags.add(parts[1])
    # Tags end in YYYY-MM-DD; lexical sort is chronological.
    return sorted(tags)[-1] if tags else None


def load_indices(s3: Any, bucket: str, tag: str) -> pd.DataFrame:
    obj = s3.get_object(Bucket=bucket, Key=f"runs/{tag}/sobol_indices.parquet")
    return pd.read_parquet(io.BytesIO(obj["Body"].read()))


# ---------- prediction checks ---------- #


@dataclass
class Check:
    name: str
    passed: bool | None  # None = UNDETERMINED (data insufficient)
    detail: str
    numbers: dict[str, Any]

    @property
    def label(self) -> str:
        if self.passed is None:
            return "UNDETERMINED"
        return "PASS" if self.passed else "FAIL"


def h1_f_arch_bay_dropout(long: pd.DataFrame) -> Check:
    """max ST of f_arch_bay across all 9 metrics < 0.02 in EVERY window."""
    per_window = long[long.parameter == "f_arch_bay"].groupby("window_start")["ST"].max().to_dict()
    threshold = 0.02
    passed = bool(per_window) and all(v < threshold for v in per_window.values())
    detail = f"max ST per window (threshold {threshold}): " + ", ".join(
        f"{w}={v:.2e}" for w, v in per_window.items()
    )
    return Check(
        "H1 (f_arch_bay dropout)",
        passed,
        detail,
        {"per_window_max_ST": {w: float(v) for w, v in per_window.items()}, "threshold": threshold},
    )


def h2_diel_phase_dominates_corr(long: pd.DataFrame) -> Check:
    """diel_phase_hours is rank-1 by ST for every (window, corr metric)."""
    sub = long[long.metric.isin(CORR_METRICS)]
    ranks: dict[tuple[str, str], int] = {}
    for (w, m), g in sub.groupby(["window_start", "metric"]):
        ordered = g.sort_values("ST", ascending=False).reset_index(drop=True)
        rk_rows = ordered.index[ordered.parameter == "diel_phase_hours"]
        ranks[(w, m)] = int(rk_rows[0]) + 1 if len(rk_rows) else -1
    n_total = len(ranks)
    n_rank1 = sum(1 for r in ranks.values() if r == 1)
    passed = n_total > 0 and n_rank1 == n_total
    detail = f"diel_phase_hours rank-1 in {n_rank1}/{n_total} (window, corr-metric) cells"
    return Check(
        "H2 (diel_phase_hours dominates corr)",
        passed,
        detail,
        {
            "rank1_count": n_rank1,
            "total_cells": n_total,
            "non_rank1_cells": {f"{w}|{m}": r for (w, m), r in ranks.items() if r != 1},
        },
    )


def h3_substrate_interaction(long: pd.DataFrame) -> Check:
    """substrate_threshold in top-3 by ST AND ST/S1 > 2.0 in every
    (window, magnitude-metric) cell."""
    sub = long[long.metric.isin(MAGNITUDE_METRICS)]
    failures: list[str] = []
    ratio_records: list[dict[str, Any]] = []
    for (w, m), g in sub.groupby(["window_start", "metric"]):
        ordered = g.sort_values("ST", ascending=False).reset_index(drop=True)
        st_row = ordered[ordered.parameter == "substrate_threshold"]
        if st_row.empty:
            failures.append(f"{w}|{m}: substrate_threshold missing")
            continue
        rank = int(st_row.index[0]) + 1
        st = float(st_row["ST"].iloc[0])
        s1 = float(st_row["S1"].iloc[0])
        ratio = st / s1 if s1 > 1e-6 else float("inf")
        ratio_records.append(
            {"window": w, "metric": m, "rank": rank, "ST": st, "S1": s1, "ST_over_S1": ratio}
        )
        if rank > 3:
            failures.append(f"{w}|{m}: rank {rank} (>3)")
        if ratio <= 2.0:
            failures.append(f"{w}|{m}: ST/S1 = {ratio:.2f} (≤2)")
    passed = not failures
    detail = (
        "all (window, magnitude-metric) pairs: substrate_threshold in top-3 AND ST/S1>2"
        if passed
        else f"{len(failures)} failing cells: {'; '.join(failures[:6])}"
    )
    return Check(
        "H3 (substrate_threshold interaction-dominated)",
        passed,
        detail,
        {"failures": failures, "per_cell": ratio_records},
    )


def h4_q10_regime_conditional(long: pd.DataFrame) -> Check:
    """Q10 mean-ST is materially higher in warm than cool windows.

    Sharpened: q10_warm_mean / q10_cool_mean > 2.0 AND
               max(Q10 mean-ST) over warm windows > 0.10.
    """
    per_window = long[long.parameter == "Q10"].groupby("window_start")["ST"].mean()
    warm = per_window[per_window.index.isin(WARM_WINDOWS)]
    cool = per_window[per_window.index.isin(COOL_WINDOWS)]
    if warm.empty or cool.empty:
        return Check(
            "H4 (Q10 regime-conditional)",
            None,
            f"insufficient windows: warm={len(warm)}, cool={len(cool)}",
            {"per_window_mean_ST": per_window.to_dict()},
        )
    warm_mean = float(warm.mean())
    cool_mean = float(cool.mean())
    warm_max = float(warm.max())
    ratio = warm_mean / cool_mean if cool_mean > 1e-6 else float("inf")
    passed = ratio > 2.0 and warm_max > 0.10
    detail = (
        f"Q10 mean-ST: warm_mean={warm_mean:.3f}, cool_mean={cool_mean:.3f}, "
        f"ratio={ratio:.2f}, warm_max={warm_max:.3f} "
        f"(need ratio>2.0 AND warm_max>0.10)"
    )
    return Check(
        "H4 (Q10 regime-conditional)",
        passed,
        detail,
        {
            "per_window_mean_ST": per_window.to_dict(),
            "warm_mean": warm_mean,
            "cool_mean": cool_mean,
            "ratio": ratio,
            "warm_max": warm_max,
            "threshold_ratio": 2.0,
            "threshold_warm_max": 0.10,
        },
    )


def h5_estuary_geography(long: pd.DataFrame) -> Check:
    """f_arch_estuary rank ≤ 2 at corr__IB CIVIC CTR AND > 2 at the
    other two corr receptors, in every window."""

    def rank_in(window: str, metric: str) -> int:
        g = long[(long.window_start == window) & (long.metric == metric)]
        ordered = g.sort_values("ST", ascending=False).reset_index(drop=True)
        rk = ordered.index[ordered.parameter == "f_arch_estuary"]
        return int(rk[0]) + 1 if len(rk) else -1

    other = ("corr__SAN YSIDRO", "corr__NESTOR - BES")
    ib = "corr__IB CIVIC CTR"
    failures: list[str] = []
    table: list[dict[str, Any]] = []
    for w in long.window_start.unique():
        r_ib = rank_in(w, ib)
        r_others = [rank_in(w, m) for m in other]
        table.append(
            {
                "window": w,
                "rank_at_IB": r_ib,
                "rank_at_SY": r_others[0],
                "rank_at_NESTOR": r_others[1],
            }
        )
        if r_ib > 2:
            failures.append(f"{w}: rank at IB = {r_ib} (>2)")
        for m, r in zip(other, r_others, strict=True):
            if 0 < r <= 2:
                failures.append(f"{w}: rank at {m} = {r} (≤2 at non-IB)")
    passed = not failures
    detail = (
        "f_arch_estuary is rank ≤ 2 at IB and > 2 elsewhere, every window"
        if passed
        else f"{len(failures)} failing checks: {'; '.join(failures[:6])}"
    )
    return Check(
        "H5 (estuary geography)", passed, detail, {"failures": failures, "per_window": table}
    )


def h6_substrate_seasonality(long: pd.DataFrame) -> Check:
    """|substrate_threshold dry_mean - wet_mean| > 0.10 (across magnitude
    metrics) → seasonal effect; else window-invariant."""
    sub = long[(long.parameter == "substrate_threshold") & long.metric.isin(MAGNITUDE_METRICS)]
    per_window = sub.groupby("window_start")["ST"].mean()
    dry = per_window[per_window.index.isin(DRY_SEASON_WINDOWS)]
    wet = per_window[per_window.index.isin(WET_SEASON_WINDOWS)]
    if dry.empty or wet.empty:
        return Check(
            "H6 (substrate seasonality)",
            None,
            f"insufficient windows: dry={len(dry)}, wet={len(wet)}",
            {"per_window_mean_ST": per_window.to_dict()},
        )
    dry_mean = float(dry.mean())
    wet_mean = float(wet.mean())
    diff = abs(dry_mean - wet_mean)
    passed = diff > 0.10
    detail = (
        f"|dry_mean - wet_mean| = {diff:.3f} "
        f"(dry={dry_mean:.3f}, wet={wet_mean:.3f}, threshold=0.10) → "
        f"{'seasonal' if passed else 'window-invariant'}"
    )
    return Check(
        "H6 (substrate seasonality)",
        passed,
        detail,
        {
            "per_window_mean_ST": per_window.to_dict(),
            "dry_mean": dry_mean,
            "wet_mean": wet_mean,
            "diff": diff,
            "threshold": 0.10,
        },
    )


# ---------- artefacts ---------- #


def write_artifacts(long: pd.DataFrame, checks: Iterable[Check]) -> None:
    OUT.mkdir(exist_ok=True)
    long.to_csv(OUT / "cross_window_st.csv", index=False)

    top5_rows: list[dict[str, Any]] = []
    for (w, m), g in long.groupby(["window_start", "metric"]):
        ordered = g.sort_values("ST", ascending=False).head(5).reset_index(drop=True)
        for rank, (_, r) in enumerate(ordered.iterrows(), start=1):
            top5_rows.append(
                {
                    "window": w,
                    "metric": m,
                    "rank": rank,
                    "parameter": r["parameter"],
                    "S1": float(r["S1"]),
                    "ST": float(r["ST"]),
                    "ST_conf": float(r["ST_conf"]),
                }
            )
    pd.DataFrame(top5_rows).to_csv(OUT / "per_window_top.csv", index=False)

    preds = [asdict(c) | {"label": c.label} for c in checks]
    (OUT / "predictions.json").write_text(json.dumps(preds, indent=2, default=str))

    md = ["# Multi-window Sobol — H1-H6 evaluation\n"]
    md.append(f"\n**Windows evaluated:** {sorted(long.window_start.unique())}\n")
    md.append("\n## Predictions\n")
    for c in checks:
        md.append(f"\n### {c.name} — **{c.label}**\n\n{c.detail}\n")
    (OUT / "summary.md").write_text("\n".join(md))


# ---------- main ---------- #


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate H1-H6 across multi-window Sobol archives.")
    ap.add_argument("--n-base-samples", type=int, default=DEFAULT_N)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--bucket", default=os.getenv("DAGSTER_S3_BUCKET"))
    ap.add_argument(
        "--tags",
        nargs="+",
        help="Pin specific archive tags (otherwise: auto-discover latest per window).",
    )
    args = ap.parse_args()

    if not args.bucket:
        print("error: --bucket or DAGSTER_S3_BUCKET required", file=sys.stderr)
        return 2

    s3 = _s3_client()
    windows = load_windows(WINDOWS_YAML)

    print(f"=== {len(windows)} windows; auto-discovering archives at s3://{args.bucket}/runs/ ===")
    tag_for: dict[str, str] = {}
    if args.tags:
        if len(args.tags) != len(windows):
            print(
                f"error: --tags has {len(args.tags)} items; need {len(windows)} "
                "(one per window in windows.yaml)",
                file=sys.stderr,
            )
            return 2
        for w, t in zip(windows, args.tags, strict=True):
            tag_for[w.start] = t
    else:
        for w in windows:
            tag = discover_archive_tag(s3, args.bucket, w, args.n_base_samples, args.seed)
            if tag is None:
                print(f"  ✗ {w.start} → {w.end}: NO ARCHIVE (skipping)")
            else:
                tag_for[w.start] = tag
                print(f"  ✓ {w.start} → {w.end}  tag={tag}")

    if len(tag_for) < len(windows):
        print(
            f"\nOnly {len(tag_for)}/{len(windows)} archives present — "
            "evaluating partial result; predictions needing missing windows "
            "will be UNDETERMINED.",
            file=sys.stderr,
        )

    frames: list[pd.DataFrame] = []
    for w in windows:
        tag = tag_for.get(w.start)
        if tag is None:
            continue
        df = load_indices(s3, args.bucket, tag)
        df["window_start"] = w.start
        df["window_end"] = w.end
        df["window_note"] = w.note
        df["archive_tag"] = tag
        frames.append(df)

    if not frames:
        print("\nerror: no archives found; nothing to compare.", file=sys.stderr)
        return 1

    long = pd.concat(frames, ignore_index=True)

    checks = [
        h1_f_arch_bay_dropout(long),
        h2_diel_phase_dominates_corr(long),
        h3_substrate_interaction(long),
        h4_q10_regime_conditional(long),
        h5_estuary_geography(long),
        h6_substrate_seasonality(long),
    ]

    print("\n=== Predictions ===")
    for c in checks:
        print(f"  {c.label:13}  {c.name}")
        print(f"                 {c.detail}")

    write_artifacts(long, checks)
    print(f"\nartifacts written to {OUT}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
