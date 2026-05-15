# Results — IB diagnostic + metric reframe

**Run on:** 2026-05-12
**Runtime:** < 2 s (no refitting; post-processes prior runs)
**Status:** ✅ **High-impact reframe.** The "IB is stuck" belief was a
            Pearson artifact. Under rank/log metrics the v3 line has
            been steadily improving all along — and SAN YSIDRO, not
            IB, is the real problem receptor.

## Question

IB CIVIC CTR's holdout Pearson r was ~0.087 across every v3.x variant.
Is the model failing on IB, or is the metric wrong?

## Key findings

### 1. IB has no independent meteorology

IB's `wind_direction_10m` / `wind_speed_10m` in
`modeldata_h2s_nofill.parquet` are byte-identical to NESTOR's
(corr = 1.000). SAN YSIDRO has its own wind (identical-fraction vs
NESTOR ≈ 0.01). Any model predicting IB is permanently limited to a
NESTOR proxy. **Data limitation, not a model bug.** Additionally IB
*leads* NESTOR by ~1 h (`corr(IB(t), NESTOR(t+1))` beats lag-0) — with
no IB-local wind this phase error is uncorrectable here.

### 2. IB is heavy-tailed; Pearson is meaningless on it

Holdout IB: median 0.5 ppb, mean 6.5, max 130. **The top 3 hours carry
40% of the obs sum-of-squares.** Pearson r is decided by whether ~3
spike hours line up — not a goodness measure for this series.

### 3. Under Spearman / log-Pearson the model is fine on IB

v3.2 (current best, single-amp diel) holdout:

| Receptor      | Pearson | Spearman | log-Pearson |
|---------------|--------:|---------:|------------:|
| IB CIVIC CTR  | 0.087   | **0.466**| 0.432       |
| NESTOR - BES  | 0.242   | 0.498    | 0.497       |
| SAN YSIDRO    | 0.200   | 0.162    | 0.226       |

IB's Spearman (0.47) ≈ NESTOR's (0.50). The model captures IB's
ordering as well as NESTOR's.

### 4. The entire v3 line's progress was under-reported

Holdout Spearman by experiment (v3 single-amp variant):

| Experiment | IB Spearman | NESTOR Spearman | SY Spearman |
|------------|------------:|----------------:|------------:|
| v3.0       | 0.337       | 0.239           | 0.059       |
| v3.1       | 0.435       | 0.356           | 0.151       |
| v3.2       | **0.466**   | **0.498**       | 0.162       |
| v3.3       | 0.460       | 0.483           | 0.156       |

Compare to the Pearson numbers we'd been reporting as headline:

| Experiment | IB Pearson | NESTOR Pearson | SY Pearson |
|------------|-----------:|---------------:|-----------:|
| v3.0       | 0.090      | 0.206          | 0.052      |
| v3.1       | 0.086      | 0.207          | 0.107      |
| v3.2       | 0.085      | 0.237          | 0.191      |
| v3.3       | 0.078      | 0.204          | 0.187      |

**IB Pearson is flat (~0.08) across the whole line while IB Spearman
climbs 0.34 → 0.47.** NESTOR Spearman doubles (0.24 → 0.50) while its
Pearson barely moves (0.21 → 0.24). The v3.2 NE-grid breakthrough — a
genuine, large improvement — was being reported at a fraction of its
real size because Pearson was the headline.

### 5. SAN YSIDRO is the real problem receptor

SY is the *only* receptor where Pearson (0.20) exceeds Spearman (0.16),
and its Spearman (~0.16) is far below IB's (0.47) and NESTOR's (0.50).
Under the appropriate metric, the project's hardest receptor is SAN
YSIDRO, not IB. The NE-grid work raised SY's Pearson but its rank-order
fit (Spearman) stayed weak — meaning v3.2 improved SY's *linear* fit
without improving its *ordering*. That's the open problem now.

## What this means

1. **Adopt Spearman as the headline calibration metric** for episodic
   H₂S fits. Keep Pearson and log-Pearson as secondary. Report all
   three (the ordering is receptor-dependent — Pearson flatters SY,
   deflates IB/NESTOR).
2. **Re-read every prior v3.x RESULTS.md with this in mind.** The
   "partial pass / small gain" verdicts were Pearson-pessimistic. The
   v3.2 NE-grid result is a major win under Spearman (IB +0.13, NESTOR
   +0.14 over v3.0).
3. **IB is solved-enough.** It's met-limited (NESTOR proxy, 1-h lead)
   and the model already captures its ordering well. Stop treating IB
   as the problem child.
4. **Redirect effort to SAN YSIDRO's rank-order fit.** SY Spearman ~0.16
   is the genuine remaining weakness. v3.2 helped SY's magnitude
   (Pearson) but not its timing/ordering. That's the next target.
5. **v2's historical "r=0.60"** was also a Pearson number on a spiky
   72-h window — not directly comparable to these holdout Spearman
   values. The project's success criteria should be restated in
   Spearman terms.

## What should be done next

1. **Restate project success metric in the service repo / docs.** A
   short PR to add Spearman + log-Pearson to
   `tijuana_dispersion`'s reported diagnostics (currently Pearson-only
   in `wind_conditional_residuals` / fit summaries).
2. **SAN YSIDRO ordering investigation.** Why does v3.2 raise SY
   Pearson but not Spearman? Likely the NE sources fixed SY's big
   spikes (magnitude) but the bulk of low-level SY hours are still
   mis-ordered. A Phase-A-style cut on SY's *non-spike* hours.
3. **Backfill Spearman into prior RESULTS.md** (or just point to this
   experiment's `metric_comparison.csv` as the canonical cross-variant
   table).
4. **Acquire IB-local met if it exists upstream.** If a real IB
   anemometer feed exists, it would lift the IB ceiling above the
   NESTOR-proxy limit. Worth asking the data provider.

## Limitations / caveats

- **Spearman has its own blind spot:** it ignores magnitude entirely.
  A model that gets ordering right but is 10× off on absolute ppb
  scores well on Spearman. log-Pearson is the better single number
  (penalises magnitude error but compresses the heavy tail). Report
  both.
- **No new fitting** — this only re-scores existing runs. If a future
  run changes the timeseries schema, update `SOURCES` in `run.py`.
- **The 1-h IB lead** is asserted from the diagnostic (prior session
  cell), not recomputed here. Re-verify if IB met provenance changes.
- **n ≈ 300 holdout hours per receptor** — Spearman is more stable
  than Pearson at this n but still a 2-week window. A longer holdout
  would firm these numbers.

## Files

- `output/metric_comparison.csv` — long-form
  experiment × variant × receptor × metric (the canonical
  cross-variant scoreboard)
- `output/summary.json` — headline reframe + recommendation flags
