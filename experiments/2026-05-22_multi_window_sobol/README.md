# Multi-window Sobol — robustness of the parameter sensitivities

**Date:** 2026-05-22 (predictions locked); run + write-up to follow on NRP
**Author:** autonomous (Claude Code session)
**Status:** pre-registered — predictions written *before* the data exists,
            so any contradiction lands as evidence (not as post-hoc
            rationalisation)
**Depends on:** PR #6 (the bulk-windows submitter + post-analysis asset
            + archival path); the existing N=8192 Mar 13–16 Sobol as
            the anchor.

## Question

The 2026-05-15 N=8192 Sobol on Mar 13–16 produced a clean picture
(`substrate_threshold` interaction-dominated for magnitude, `diel_phase_hours`
first-order for shape, `f_arch_bay` ≈ 0, `Q10` surprisingly small).
**Are those findings robust across regimes/seasons, or are they
window-specific?** A six-window sweep at the same N + seed isolates the
"window effect" cleanly.

## Approach

`submit_sobol.py --windows-file windows.yaml` → six sequential N=8192
Saltelli sweeps; each producing a durable archive at
`s3://tj-calibration/runs/<tag>/`. Then `compare.py` loads the six
archives, computes the H1–H6 predictions below as PASS/FAIL, and
writes `output/predictions.json` + `output/cross_window_st.csv` +
`output/summary.md`. The pre-registered predictions are the
load-bearing artifact — they go on the record now.

Windows (see `windows.yaml` for the exact dates):

| Class | Windows |
|---|---|
| **Cool / advective** (calibration arc baseline regime) | 2026-03-13 (anchor), 2026-02-08 |
| **Warm / stagnation-heavy** (calibration arc "event" regime) | 2025-09-01 (summer high-T), 2026-04-04 (752 ppb all-time max), 2026-05-10 (Berry events) |
| **Cool / event** | 2025-12-20 (4 winter events) |

Same seed (42) across all windows so parameter samples are identical;
variance comes entirely from the fit window. Same `N=8192` so CIs are
comparable.

## Pre-registered predictions (each = one number, PASS/FAIL)

These commit to specific claims *before* the data exists, so the
comparison is honest by construction.

### H1 — `f_arch_bay` is globally inert (dropout candidate confirmed)
`max ST` of `f_arch_bay` across all 9 metrics stays **< 0.02** in
**every** window.
- **Baseline (Mar 13-16):** 5 × 10⁻⁶ — passes trivially.
- **If H1 passes** in all 6 windows: defensible global drop. Reduces the
  parameter set 11 → 10 for any follow-on MCMC / LOO-CV.
- **If H1 fails** anywhere: keep `f_arch_bay`; report which window(s) lit it up.

### H2 — `diel_phase_hours` dominates shape fit, everywhere
For every (window, `corr__*` metric) pair, `diel_phase_hours` is rank-1
by ST. Total: 6 windows × 3 corr metrics = 18 checks; all must pass.
- **Baseline:** rank-1 at all 3 receptors on Mar 13-16 (ST 0.77, 0.49, similar at SY).
- **Strong claim**, on purpose. The diel-timing finding is the
  calibration arc's most cited positive; this is the falsification test.

### H3 — `substrate_threshold` is structurally interaction-dominated
For every (window, magnitude metric) pair (6 windows × 6 metrics =
36 checks): `substrate_threshold` is in the top-3 by ST **AND**
`ST / S1 > 2.0`.
- **Baseline:** ST/S1 ≈ 3 at every Mar 13-16 magnitude metric.
- **If H3 passes**: the LHS-Pearson 3× underestimate is a structural
  property of variance-based vs univariate SA, not a window artifact.

### H4 — `Q10` is regime-conditional (sharpened)
- Let `q10_warm_mean` = mean of `Q10`'s mean-ST over the warm windows
  (Sep 2025, Apr 2026, May 2026).
- Let `q10_cool_mean` = mean over cool windows (Mar 2026, Feb 2026).
- PASS iff **`q10_warm_mean / q10_cool_mean > 2.0`** AND
  **`max Q10 mean-ST across warm windows > 0.10`**.
- **Baseline (Mar 13-16, cool):** mean ST = 0.04.
- **If H4 passes:** vindicates the calibration-arc reading that
  temperature is *the* calm-night driver but gets diluted in
  whole-window Sobol over cool periods. Closes the apparent Q10/Sobol
  paradox cleanly.
- **If H4 fails** (Q10 stays small even in warm/stagnation windows):
  the attribution-vs-Sobol reconciliation is wrong and needs
  re-examination. This is the genuinely surprising failure case worth
  watching for.

### H5 — `f_arch_estuary` is geography-real, not noise
For every window:
- `rank(f_arch_estuary)` in `corr__IB CIVIC CTR` is **≤ 2**.
- `rank(f_arch_estuary)` in both `corr__NESTOR - BES` and
  `corr__SAN YSIDRO` is **> 2** (mid-pack).
- **Baseline:** rank-1 at IB (ST 0.36), rank-4+ at NESTOR (ST 0.12).
- Tests whether the receptor-specific finding is a genuine geographic
  signal (IB sits closest to estuary outlets) or a sampling artifact.

### H6 — `substrate_threshold` is seasonally variable (new)
SBIWTP throughput varies seasonally: wet (Dec, Feb) → high flow → low
substrate buildup; dry (Sep, May) → low flow → high buildup. Comparing
`substrate_threshold` mean ST across the magnitude metrics:
- `dry_mean` = mean over {Sep 2025, May 2026}.
- `wet_mean` = mean over {Dec 2025, Feb 2026}.
- PASS (seasonal) iff **`|dry_mean - wet_mean| > 0.10`** (either direction).
- FAIL (window-invariant) otherwise.
- **Calibration implication:** if PASS, future calibrations should let
  the substrate term float per-season; if FAIL, a single global
  parameter is justified across the year.

## Reproduce

```bash
# 1. Sanity-check the YAML (no submission, just print the plan):
uv run python nrp/scripts/submit_sobol.py \
    --windows-file experiments/2026-05-22_multi_window_sobol/windows.yaml \
    --dry-run

# 2. Live submission (requires Dagster daemon on NRP + port-forward):
kubectl port-forward svc/dagster-dagster-webserver 3000:80 -n ucsd-center4health &
sleep 3
uv run python nrp/scripts/submit_sobol.py \
    --windows-file experiments/2026-05-22_multi_window_sobol/windows.yaml
kill %1 2>/dev/null

# 3. After the 6 archives land in s3://tj-calibration/runs/<tag>/:
source nrp/.env
uv run python experiments/2026-05-22_multi_window_sobol/compare.py

# 4. Hand-author RESULTS.md from output/summary.md + output/predictions.json.
```

`compare.py` auto-discovers the latest archive matching each window's
`(start, end, N=8192, seed=42)` tuple under `s3://<bucket>/runs/`.
Reproducibility: pass `--tags <tag1,tag2,...>` to pin specific
archives.

## Files

- `windows.yaml` — the 6-window input.
- `compare.py` — H1-H6 PASS/FAIL evaluator.
- `RESULTS.md` — placeholder with the predictions repeated; filled in
  after the run.
- `output/` (gitignored) — `predictions.json`, `cross_window_st.csv`,
  `per_window_top.csv`, `summary.md`, optional heatmap PNG.
