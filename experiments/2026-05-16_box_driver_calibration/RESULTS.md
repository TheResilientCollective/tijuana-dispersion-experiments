# Results — box + temperature-led driver calibration

**Run on:** 2026-05-16
**Runtime:** ~3 min
**Status:** ✅ **Qualified positive.** The calibrated box→driver
**clears the constant-box rank-skill ceiling (~2×)** and hits the
attribution-predicted temperature ceiling / the floor of the design
target. ❌ It does **not** solve the magnitude problem: recall@100 = 0,
extremes under-predicted ~17–20×. The line is a validated **calm-night
*ranker***, not an absolute-ppb predictor.

## Setup

Shipped v0.4.0 model. 12 964 Berry hours, 242 > 100 ppb.
Chronological 70/30 — identical split to `box_calibration` /
`emission_driver_attribution`, so numbers compare directly.
`T_ref`=20 °C (absorbed into E0, non-identifiable), `area`/`H_mix`
shipped defaults, `E0` closed-form, substrate off (attribution
already measured it < 0.11). Decisive statistic = amplitude-invariant
held-out rank-skill ceiling over the Q10×τ grid.

## Held-out test results

| Regime | model | held-out Spearman | recall@100 | median pred / obs at >100 |
|---|---|--:|--:|--:|
| `is_stagnation` | constant box (#3, *before*) | 0.120 | 0.00 | 10.6 / 177.1 |
| `is_stagnation` | **driver box — rank ceiling** | **0.271** @ Q10=5, τ=12 | — | — |
| `is_stagnation` | driver box — RMSE point est. | 0.169 @ Q10=1.5 | 0.00 | 10.5 / 177.1 |
| `stable_atm` | constant box (#3, *before*) | 0.185 | 0.00 | — |
| `stable_atm` | **driver box — rank ceiling** | **0.338** @ Q10=5, τ=12 | — | — |

| Bar | operational | `stable_atm` |
|---|--:|--:|
| Constant-box ceiling (prior) | 0.127 | 0.218 |
| **Driver-box rank ceiling (this)** | **0.271** | **0.338** |
| Δ (clears by) | **+0.144** | **+0.120** |
| Design target | 0.3–0.5 | 0.3–0.5 |

### Event validation (shipped `run_forward`, end-to-end, May 10–11)

```
observed peak           177.1 ppb
constant box (#3)          9.2 ppb
driver box (#6, calibrated) 7.7 ppb     emission_driver=true, dispatch="regime"
```

## What this means

1. **The driver works for *ranking* — as designed and predicted.**
   Held-out rank skill ~doubles (0.127→0.271, 0.218→0.338), clearing
   the constant-box ceiling decisively and reaching the ~0.33
   `temperature_2m` upper bound from attribution and the floor of the
   0.3–0.5 design target. The box→driver structure is the right model
   for *ordering which calm nights are worse* — operationally useful
   for prioritisation / early-warning.

2. **The objective changes the calibrated Q10 — report the
   rank-optimal.** RMSE-optimal Q10 = 1.5 (Spearman only 0.17): least
   squares is dominated by the low-concentration calm bulk and
   *under-uses* temperature. Rank-optimal Q10 = 5.0 (Spearman
   0.27/0.34). For the operational goal (rank severity) the
   steep-Q10 rank-optimal is the right calibration; Q10≈5 sits at the
   physical edge for microbial sulfate reduction (typical 2–4), so
   ~0.27–0.34 is a *physically-bounded* characterisation — pushing
   Q10 higher would be unphysical curve-fitting, not skill.

3. **The magnitude problem is unsolved.** recall@100 = 0.00 in every
   configuration; median predicted at the >100 ppb hours ≈ 9–10 ppb
   vs ≈ 167–177 observed (~17–20× short); the May 10–11 event peak
   (7.7 ppb) is *no better* than the constant box (9.2) and ~23× short
   of 177. A single LSQ amplitude cannot span the 1→750 ppb dynamic
   range: fitting the hundreds of ~1–10 ppb calm hours forces the
   amplitude far below what the spikes need. Temperature reorders the
   nights correctly but does not inflate the extreme magnitudes.

4. **Where the remaining skill lives.** Attribution's autoregressive
   reference (`h2s_lag_1h` ≈ 0.70) bounds total predictability;
   temperature ranking tops out ≈ 0.34. The ≈ 0.36 gap is **not**
   recoverable by more emission-driver tuning (Spearman already
   pegged Q10 at the physical edge): it is episodic/triggered
   persistence the smooth temperature term cannot represent. Closing
   it needs an *event/trigger* mechanism, not a hotter Q10.

## Verdict

**The box→driver line is validated for what it was designed to do and
no more.** It is the correct calm-night *structure* and a usable
*relative severity ranker* (held-out Spearman ~0.27–0.34, ~2× the
constant box, at the attribution-predicted ceiling). It is **not** an
absolute-concentration predictor in the extreme regime and must not be
shipped or reported as one (recall@100 = 0). This closes the
"temperature-led emission driver" line on a qualified positive:
necessary structure achieved, magnitude gap explicitly characterised
and attributed to episodic persistence rather than emission scaling.

## Next

1. **Operational framing (service):** expose the box→driver as a
   calm-night **risk *rank*/percentile**, not a ppb point estimate;
   keep `out_of_envelope` / `stagnation_flags` as the magnitude
   honesty guardrail (issue #2 already does this). A short design
   note, not new physics.
2. **Magnitude line (new experiment, not emission-driver tuning):**
   test an *event-trigger* amplitude — e.g. box `E_local` gated by an
   episodic flag (flow/SBIWTP spike, or the autoregressive
   `h2s_lag`-style persistence) — explicitly targeting recall@100,
   reported against this run as the baseline.
3. **`stable_atm`** remains the better regime signal (0.34 vs 0.27);
   folding it into the service classifier is still the standing
   recommendation (carried from the calm-night reanalysis).

## Limitations

- Single receptor (Berry) by design. Train/test chronological; the
  rank ceiling is low on *both* splits so the conclusion is not a
  split artefact.
- Q10 grid capped at 5.0 (≥ physical plausibility); pegging is
  reported honestly — higher Q10 is curve-fitting, not skill, and
  cannot close the magnitude gap (recall@100 = 0 regardless).
- `T_ref` non-identifiable from one receptor (absorbed into E0) —
  stated, not worked around; it does not affect rank skill.

## Files

- `output/summary.json` — full per-regime metrics, ceiling, point
  estimate, and the end-to-end event validation.
