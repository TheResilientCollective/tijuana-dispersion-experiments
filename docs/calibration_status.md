# Calibration Status Log

This is the running log of where the H₂S dispersion calibration stands. **Read this first** at the start of any session. Update it after every meaningful experiment.

Format for each entry:

```
## YYYY-MM-DD — <experiment short name>

**Question**: ...
**Result**: ...
**State change**: <what we now believe vs before>
**Next**: <what experiment this points toward>
```

Don't delete old entries. The log is the project's memory.

---

## 2026-05-12 — ib_metric_reframe (IB diagnostic → project-wide metric change)

**Question**: IB CIVIC CTR's holdout Pearson r was stuck at ~0.087
across every v3.x variant. Is the model failing on IB, or is the
metric wrong?

**Result**: The metric was wrong. Three things established:

1. **IB has no independent meteorology.** Its wind columns in
   `modeldata_h2s_nofill.parquet` are byte-identical to NESTOR's
   (corr=1.000). SAN YSIDRO has its own wind; IB does not. IB also
   *leads* NESTOR by ~1 h. Both are uncorrectable data limitations.

2. **IB is heavy-tailed (median 0.5, max 130 ppb); top 3 hours = 40%
   of sum-of-squares.** Pearson r on this series is decided by ~3
   points and is not a goodness measure.

3. **Under Spearman the model is fine on IB and the whole v3 line was
   under-reported.** v3.2 holdout: IB Pearson 0.087 vs **Spearman
   0.466** (≈ NESTOR's 0.498). Across the line, IB Spearman climbs
   0.34 (v3.0) → 0.47 (v3.2) while IB Pearson stays flat ~0.08.
   NESTOR Spearman doubles 0.24 → 0.50 while its Pearson barely moves.
   **The v3.2 NE-grid breakthrough was real and large; Pearson hid it.**

**State change** (this reorders project priorities):
- **Spearman becomes the headline calibration metric** for episodic
  H₂S fits; Pearson + log-Pearson secondary. Report all three —
  ordering is receptor-dependent (Pearson flatters SY, deflates
  IB/NESTOR).
- **IB is no longer the problem receptor.** It's met-limited and the
  model already captures its ordering (~0.47 Spearman). Stop chasing
  IB.
- **SAN YSIDRO is the real problem receptor.** It is the only receptor
  where Pearson (0.20) > Spearman (0.16); its Spearman ~0.16 is far
  below IB/NESTOR (~0.47-0.50). v3.2 raised SY *magnitude* (Pearson)
  but not *ordering* (Spearman). That is the open problem.
- Every prior v3.x RESULTS.md verdict was Pearson-pessimistic. The
  canonical cross-variant scoreboard is now
  `experiments/2026-05-12_ib_metric_reframe/output/metric_comparison.csv`.

**Next**:
1. Restate the project success metric (small service-repo PR: add
   Spearman + log-Pearson to the reported fit diagnostics, currently
   Pearson-only).
2. SAN YSIDRO ordering investigation — why did v3.2 lift SY Pearson
   but not Spearman? Phase-A-style cut on SY's *non-spike* hours.
3. Backfill Spearman into the project's reporting / docs.
4. Ask the data provider whether a real IB-local anemometer feed
   exists (would raise the IB ceiling above the NESTOR-proxy limit).

---

## 2026-05-12 — autonomous-session summary (Phase A through v3.3)

For convenience: this is a roll-up of everything the autonomous Claude
Code session ran on 2026-05-11 / 2026-05-12 while @valentinedwv was on
vacation. The individual entries below carry the detail.

### State of the calibration on Apr 1-14 holdout

| Variant | SAN YSIDRO | NESTOR-BES | IB CIVIC CTR |
|---------|------:|------:|------:|
| v3 (Mar 13-15 only, original report) | (n/a) | 0.60 | 0.62 |
| v3 refit on broader windows (no NE sources)         | 0.041 | 0.201 | 0.091 |
| v3.1 (2 NE candidates, relaxed bay cap, single-amp diel) | 0.114 | 0.211 | 0.086 |
| v3.2 (12-NE-grid, single-amp diel) ← current best     | **0.200** | **0.242** | 0.087 |
| v3.3 (spill-excluded, single-amp diel)                | 0.198 | 0.218 | 0.082 |

SAN YSIDRO holdout fit improved 5× over the original v3 baseline.
NESTOR-BES climbed by 0.04. IB CIVIC CTR is the remaining problem
receptor (stuck at 0.087 regardless of every variant tried).

### Things we now believe

1. **There is a real source near (32.575, -117.040)** — directly north
   of SAN YSIDRO in the Otay Mesa industrial area. The v3.2 grid sweep
   spontaneously attributed 0.89 g/s to that cell, with 4.5 g/s total
   across the NE grid. Worth physical ground-truthing.
2. **A secondary source candidate near (32.610, -117.060)** on the
   south edge of San Diego Bay also lights up at 0.87 g/s.
3. **The bay archetype default cap (0.5 g/s) is too tight.** Otay River
   Outlet readily wants 0.9 g/s in v2-style fits. Worth a service-repo
   PR to raise the default to ~2.0.
4. **The v2-era Mar 13-15 numbers were window-specific.** v2's
   originally-reported r=0.60 (NESTOR) etc. were on a 72-hour
   spill-event window. Refit on the broader Feb-Mar window v2's r is
   0.39 / 0.15 / 0.27. Future calibration reports should default to
   holdout windows.
5. **Per-archetype-amplitude diel is a dead end.** Three experiments
   show it doesn't beat single-amp diel on holdout. Land vs water
   amplitude split is retired.
6. **Spill exclusion is a dead end.** The Mar 13-15 spill carries
   information that generalises to non-spill nocturnal regimes; v3.3
   confirms excluding it hurts holdout fit (NESTOR drops 0.02-0.04).
   The spill's signal got absorbed by *channel* sources, not Stewart's
   Drain (the documented spill source).

### Next-priority experiments (queued, not yet run)

1. **IB CIVIC CTR diagnostic** — the receptor stuck at holdout r ~0.08
   across every v3.x variant. A Phase-A-style sector decomposition for
   IB. Likely highest-leverage remaining single experiment.
2. **Refine NE grid** at 0.5 km spacing around (32.575, -117.040) and
   (32.595, -117.040). Narrows the source location further.
3. **Investigate channel-source rate inflation.** v3.3 showed channel
   sources absorb 3 g/s; this is implausibly high for 12 distributed
   "bridge / crossing" points. Either reduce the count or tighten
   bounds.
4. **Ground-truth (32.575, -117.040)** against SDAPCD industrial
   inventory, cross-border emission reports, Otay Mesa zoning.
5. Open issue: investigate physical sources colocated with NE hot
   cells (separate research task).

### Files added in this session

- `experiments/2026-05-11_calibration_v3/` — initial diel experiment
- `experiments/2026-05-11_sy_north_residual_diagnostic/` — Phase A
- `experiments/2026-05-11_calibration_v3_1/` — per-arch diel + 2 NE
- `experiments/2026-05-12_calibration_v3_2/` — 12-grid NE sweep
- `experiments/2026-05-12_calibration_v3_3_spill_exclude/` — spill exclusion

---

## 2026-05-12 — calibration_v3.3 (spill exclusion, negative result)

**Question**: Does excluding the documented Mar 13-15 spill from
training give lower drain rates and better holdout generalisation?

**Result**: No on both counts.
- Drain rates are essentially unchanged (Stewart's Drain stays at
  0.05-0.07 g/s; total drain rate 4.08 → 4.07). The hypothesis that
  the spill inflated drains was wrong: NNLS never attributed the spill
  to Stewart's Drain in the first place.
- **Channel sources** absorbed the spill's signal instead — total
  channel rate drops 3.02 → 1.81 g/s (−40%) when the spill is excluded.
  Suggests the wind direction during the spill peak hours was not
  consistent with Stewart's→NESTOR bearing, so NNLS spread the mass
  upstream onto channel sources.
- Holdout fit regresses across all three variants: NESTOR-BES r drops
  0.02-0.04. SAN YSIDRO is essentially unchanged.

**State change**:
- The hypothesis "spill inflates drain rates" is rejected.
- The Mar 13-15 spill carries information useful for non-spill
  nocturnal regimes — its inclusion improves holdout. Counter-
  intuitively, removing the most extreme event hurts generalisation.
- The "spill archetype" idea (cap 20 g/s, event-windowed activation)
  in the service repo's defaults is unmotivated by this evidence —
  NNLS doesn't even attribute the actual documented spill to its
  source.
- Channel-source rate inflation is the more worrying finding. 3 g/s
  across 12 distributed bridge/crossing points is implausibly high
  for the underlying physics — these are tagged as channel sources
  but their fitted rates approach drain magnitudes.

**Next**: Stop chasing spill exclusion. Look at IB CIVIC CTR
(stuck at r=0.08) and channel-source overfit instead.

---

## 2026-05-12 — calibration_v3.2 (NE candidate grid sweep)

**Question**: v3.1 added 2 fixed NE candidates (~1.8 g/s absorbed total)
but the SY N-residual stayed at ~12 ppb. Does a 12-cell grid sweep
across the Otay Mesa / cross-border area find a coherent source
location?

**Result**: Yes — and the spatial structure is sharp. On the Apr 1-14
holdout SAN YSIDRO r climbs from 0.115 (v3.1, 2 candidates) to 0.200
(v3.2, 12-grid + single-amp diel). Cumulative from the original v3
(no NE sources): 0.041 → 0.200, a **5× improvement on SY**.
NESTOR-BES holdout r climbs from 0.21 → 0.24 in parallel.

Fitted rates show two dominant grid cells:
- `ne11` at (32.575, -117.040) = 0.89 g/s — directly **north of SAN
  YSIDRO** by ~2 km; centred in Otay Mesa industrial zone.
- `ne30` at (32.610, -117.060) = 0.87 g/s — far NW, south edge of San
  Diego Bay.

Total NE absorption in v2-style fit: 4.51 g/s (vs 1.8 g/s with v3.1's
2 fixed candidates). NNLS spontaneously builds a coherent spatial
pattern when given freedom; this is strong evidence the source
geometry is real, not a fitting artefact.

**Side observation**: per-archetype-amplitude diel (v3.1) still does
not beat single-amp diel (v3) on holdout, even with the richer grid.
The land/water split is consistently a small holdout regression.
Stop spending time on that variant — single-amp wins.

**State change**:
- We now strongly believe there's a real H₂S source near
  (32.575, -117.040). Otay Mesa industrial / cross-border. Worth
  physical ground-truthing.
- A secondary source candidate near (32.610, -117.060) on the south
  edge of San Diego Bay also lights up.
- Per-archetype diel is *retired* as a hypothesis. Going forward,
  single global amp + phase is the canonical diel form.

**Next**:
1. Refine grid in the hot zone (25 cells at 0.5 km spacing around
   the two hot spots).
2. v3.3: spill exclusion — remove documented spill hours from
   training; check drain rate inflation.
3. v3.4: IB CIVIC CTR diagnostic. Holdout r stuck at 0.087 regardless
   of variant.
4. Ground-truth (32.575, -117.040) against SDAPCD industrial inventory
   and cross-border emission reports.

---

## 2026-05-11 — calibration_v3.1 (per-archetype diel + relaxed bay cap + candidate NE sources)

**Question**: Phase A diagnostic ([2026-05-11_sy_north_residual_diagnostic](../experiments/2026-05-11_sy_north_residual_diagnostic/))
identified two issues v3 didn't fix: the bay archetype cap was binding,
and SAN YSIDRO showed a uniquely strong N-sector signal no existing
source could explain. v3.1 changes three things at once: raise bay cap
(0.5 → 5.0 g/s), add two hypothesized NE-of-SAN-YSIDRO sources
(`northeast` archetype, cap 2.0 g/s), and split the diel amplitude into
land vs water.

**Result**: On the Apr 1-14 holdout window:
- SAN YSIDRO r: 0.041 (original v3 source field) → 0.092 (v2 fit with
  the new source field, no diel) → 0.114 (v3 single-amp diel) → 0.115
  (v3.1 per-archetype diel).
- Per-archetype diel adds essentially nothing on top of single-amp diel
  on this holdout window — the model isn't expressive enough yet for
  the land/water split to matter.
- **The dominant lift (more than doubling SY holdout r) comes from
  adding NE candidates + relaxing the bay cap** — neither of which is
  about temporal modulation. The "structural" fix dominates the
  "parametric diel" fix.

NE candidate fitted rates (v2-style, no diel): Otay Mesa Industrial S =
0.83 g/s, Otay Mesa Industrial N = 0.98 g/s. Neither hit its 2.0 cap.
NNLS spontaneously attributes ~1.8 g/s to hypothesized sources NE of
SAN YSIDRO — strong indirect evidence of a real source in that region.

The v3.1 fit hits `amp_water = 3.5` at its upper bound, signalling that
water-side sources want even stronger nocturnal amplification.

**State change**:
- We now believe there is a real source (or set of sources) NE of SAN
  YSIDRO with ~1-2 g/s combined H₂S emissions. Otay Mesa industrial
  area is the prime candidate region.
- We now believe the bay archetype default cap of 0.5 g/s in
  `tijuana_dispersion.calibration.ARCHETYPE_BOUNDS_G_S` is too tight;
  ~2.0 would be a better default (worth a service-repo PR).
- We now believe per-archetype-amplitude diel is **not** a worthwhile
  refinement until the spatial source field is more complete. The
  signal-to-noise on splitting the diel modulator is below the
  spatial-correction signal.

**Next**:
1. v3.2 — expand the NE candidate grid (6-9 sources across the Otay
   Mesa region). NNLS will reveal which locations light up.
2. v3.3 — raise `amp_water` ceiling beyond 3.5, see if performance
   keeps climbing or stabilises.
3. v3.4 — exclude the documented Mar 13-15 spill from training; check
   whether the inflated drain rates were spill-event artefacts.
4. IB CIVIC CTR–specific diagnostic — this receptor stays stuck at
   holdout r ~ 0.09 regardless of variant; needs its own work.

---

## 2026-05-11 — sy_north_residual_diagnostic (no-fitting analysis)

**Question**: Where does the SAN YSIDRO N/NE-wind residual seen in v3
come from?

**Result**: Two distinct findings. (1) The v3 NNLS hit the bay
archetype upper bound (0.5 g/s) on the Otay River Outlet bay source —
the cap is the binding constraint, not source physics. Relaxing it
should let more N-wind NESTOR signal get absorbed. (2) In the N and
NNW wind sectors, SAN YSIDRO is uniquely elevated (30 ppb mean) while
NESTOR is much lower (13 ppb) and IB sees essentially zero — opposite
to every other sector. That geometric signature requires a source
*east or north of SAN YSIDRO*, which no existing modelled source
satisfies (all sources are in the river valley, *west* of SAN YSIDRO).

**State change**:
- The v2-era diagnostic "W/SW over-prediction at SAN YSIDRO" was
  window-specific to Mar 13-15. On the broader Apr 1-14 holdout the
  *northern* residual is much larger (~12 ppb mean vs ~1.5 ppb in
  W/SW).
- The dominant fix is structural (add missing sources / relax bounds),
  not parametric (diel modulation).

**Next**: v3.1 implements both fixes simultaneously (see entry above).

---

## 2026-05-11 — calibration_v3 (diurnal modifier)

**Question**: Does adding `f_diel(t)` on emission rates fix v2's
SAN YSIDRO W/SW over-prediction and the IB CIVIC CTR magnitude/timing
mismatch identified by the sensitivity LHS?

**Result**: Partial pass. v3 fits `diel_amplitude=1.75`, `phase=4:10 am`
on Feb 1 – Mar 31, 2026; holdout on Apr 1-14. SAN YSIDRO holdout r
improves from 0.041 (v2 refit) to 0.063 (v3); NESTOR-BES from 0.201
to 0.211; IB CIVIC CTR essentially unchanged (0.091 → 0.088). However,
the W/SW residual at SAN YSIDRO — the load-bearing acceptance criterion —
grew from +1.39 to +1.76 ppb (got *worse*). Importantly, v2's
originally-reported r=0.60/0.62 numbers were on the 72-hour Mar 13-15
spill window; refit on the full Feb-Mar window v2's r is 0.39/0.15 at
NESTOR/IB. The 2-month window is a much harder fit than v2 communicated.

**State change**:
- We now believe the diel modifier was the right shape of fix for the
  v2 Mar 13-15 diagnostic but not for the *dominant* residual seen on
  a broader holdout. The Apr 1-14 SAN YSIDRO residual is dominated by
  *northern* winds where the model has zero sources and predicts ~0
  while obs is 6-30 ppb. That points to a missing source east or NE of
  SAN YSIDRO (Otay Mesa industrial? cross-border emission? local
  background?), not a temporal-modulation problem.
- We now believe v2's Mar 13-15 metrics were upper-bounded by the spill
  event boosting signal. Going forward, calibration reports must include
  holdout window numbers by default.

**Next**:
1. Investigate the SAN YSIDRO N/NE residual: identify candidate sources,
   pull weather-station data colocated with SY to verify wind reading
   isn't the issue.
2. Per-archetype diel (drain/channel vs estuary) — currently a single
   global multiplier.
3. Expand outer optimization to include Q₁₀ and substrate params.
4. Add a "background" or "Otay Mesa" source east of SY and refit.

---

## 2026-05-05 — sensitivity_lhs

**Question**: Which emissions-model parameters most influence the fit?

**Result**: 200-sample Latin Hypercube across 11 emissions parameters, evaluated on the Mar 13-15 window using the Gaussian plume backend. `f_arch_estuary` is the dominant single sensitivity (Pearson r=-0.64 against NESTOR's correlation metric). Counter-intuitively, IB CIVIC CTR's *timing* fit prefers more drain weight and less estuary weight (r=+0.30 and r=-0.35 respectively) — opposite to v2's NNLS attribution. v2 fit IB's magnitude well via estuary weight, but at the cost of phase.

**State change**: We now believe v2's estuary-heavy attribution at IB is a magnitude-driven artifact of the time-invariant model, not a real geophysical signal. The diurnal modifier is the right fix because the W-wind over-prediction at SAN YSIDRO is the same artifact in mirror image. Both stations need temporally-varying source weights to fit timing and magnitude jointly.

**Next**: Implement a diurnal modifier on emission rates (v3). Re-run on Mar 13-15 to confirm IB attribution shifts toward drains as predicted.

---

## 2026-05-05 — calibration_v2

**Question**: Does adding distributed sources (12 channel + 9 estuary grid) plus archetype-bounded NNLS materially improve fit at IB CIVIC CTR?

**Result**: Yes. r=0.07 → r=0.62 at IB CIVIC CTR. NESTOR fit slightly worse (0.60→0.56) due to physical bounds preventing v1's 40 g/s phantom rates. SAN YSIDRO regressed (0.27→0.12) due to the time-invariant model overpredicting during W-wind regimes when channel sources should have been quiet (daytime). Wind-conditional residual diagnostic surfaced this as +20 ppb over-prediction at SAN YSIDRO with W and SW winds.

**State change**: Distributed estuary sources are a real geophysical feature, not a model artifact. Time-invariant emissions cannot fit IB and SAN YSIDRO simultaneously. Bounded NNLS works (no more phantom rates) but the bounds also reveal that 11/38 sources hit their upper limit — a signal that some baseline rates need event-conditional relaxation (e.g., a "spill" archetype with cap 20 g/s, active only during documented event windows).

**Next**: This pointed to the sensitivity analysis (above) and to the diurnal modifier as v3's core addition.

---

## 2026-05-05 — demo_v1 (baseline)

**Question**: Does the dispersion service pipeline work end-to-end on real data, with reasonable physics?

**Result**: Yes. Forward Gaussian plume + naive NNLS inversion ran in ~50 ms over a 72-hour window. NESTOR fit r=0.60. SAN YSIDRO r=0.27. IB CIVIC CTR r=0.07. Several sources received unconstrained fitted rates of 30-40 g/s — physically absurd, motivating archetype bounds in v2.

**State change**: The forward physics is correct (Gaussian plume rotation, σ coefficients, ground reflection). The NNLS inversion is also correct given its inputs. The problem is upstream: insufficient sources and unconstrained rates.

**Next**: v2 (above).

---

## Open questions (not yet experiments)

These are flagged for future investigation. Don't guess; design an experiment that resolves the question.

- **Mixing height**: the current plume code assumes unbounded vertical mixing. Under nocturnal stable conditions the actual mixing height collapses to ~50-200 m, which would amplify ground-level concentrations 5-10× from the same emissions. Possible explanation for why v2's fitted rates are 100× the literature priors. *Experiment to design*: integrate a mixing-height cap into `core.py` and re-fit Mar 13-15 with literature-default rates; see if fit improves.

- **Wind data quality during calm nights**: the wind-conditional residual table for NESTOR shows +125 ppb under-prediction during "S" wind hours. Three of those hours; with mean reported wind 1.5 m/s. Calm-night anemometer readings are notoriously unrepresentative because surface eddies dominate. *Experiment to design*: pull NERR (TJRTLMET) hourly winds for the same window and compare to Open-Meteo; if NERR shows different directions, the residual is met-error, not source attribution.

- **Substrate model parameterization**: the inverse-SBIWTP form `f_substrate = 1 + α × max(0, threshold - flow)` is a placeholder. The geodemic-repo emissions model has a more developed form. *Experiment to design*: port the geodemic substrate function into the bridge hook in `emissions.py`, calibrate the rest of the parameters with substrate held to that form, and compare.
