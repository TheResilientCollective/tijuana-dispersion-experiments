# Results — event-trigger magnitude

**Run on:** 2026-05-16
**Runtime:** ~4 min
**Status:** ❌ **Decisive negative for exogenous triggers.** The only
signal with magnitude skill is autoregressive (a nowcast, not a
forward model). This is the **capstone** of the calm-night calibration
arc.

## Setup

Calibrated driver (Q10=5, τ=12), shipped v0.4.0 box via the #6
`substrate` multiplier. 12 964 Berry hours, 242 > 100 ppb.
Chronological 70/30 — comparable to all prior experiments. Train
objective Youden's J@100 (not gameable by blanket boosting).

## Held-out test (operational `is_stagnation`; `stable_atm` materially identical)

| Trigger | recall@100 | precision@100 | FPR | F1 | Spearman |
|---|--:|--:|--:|--:|--:|
| none (calibrated driver baseline) | 0.00 | 0.00 | 0.00 | 0.00 | 0.271 |
| **best EXOGENOUS** (sbiwtp_deficit, p98, B=10) | **0.00** | **0.00** | 0.00 | 0.00 | 0.269 |
| AUTOREGRESSIVE ref (`h2s_lag_1h`, p95, B=100) | **0.211** | **0.349** | 0.059 | 0.263 | 0.442 |

`stable_atm`: exogenous **0.00 / 0.00**; autoregressive **0.218 / 0.338**, Spearman 0.459.

## What this means

1. **No exogenous trigger fires on the right hours.** Across 7
   forward-usable episodic features × 4 percentiles × 5 boosts, the
   best train Youden J is ≈ 0.02 and held-out recall@100 = **0.00**
   with precision 0.00. The flow/SBIWTP/precip episodics in this
   dataset carry no information about *which* calm hours go > 100 ppb.
   This is consistent with attribution (all such features had solo
   Spearman < 0.11) and now closes it for the *magnitude* question
   too: it is not a thresholding/parameterisation problem, the signal
   is absent.

2. **Only autoregressive persistence has magnitude skill — modest, and
   not a forward signal.** Triggering on recent *observed* H2S
   (`h2s_lag_1h`) recovers ~21 % of extremes at ~35 % precision
   (FPR ~6 %, Spearman ~0.45). Real but limited, and by construction
   it cannot forecast cold-start — it only *extends an event already
   in progress*. That is a **nowcast/persistence model**, a
   fundamentally different product from a forward
   dispersion+emissions model.

3. **Capstone conclusion of the calm-night arc.** Berry's > 100 ppb
   nocturnal extremes are **not predictable from any exogenous input
   available in this dataset** — not advection (v3 → v3.6), not the
   constant box (`box_calibration`), not the temperature emission
   driver (`box_driver_calibration`: ranks, no magnitude), not any
   exogenous episodic trigger (this run: recall@100 = 0). The forward
   model's ceiling in this regime is **ranking** (Spearman ≈ 0.27–0.34);
   **magnitude is only reachable autoregressively**, and even then
   modestly (recall ≈ 0.21).

## Recommendation (actionable, no further calibration on this data)

1. **Service posture is already correct — keep it.** The issue-#2
   guardrail (`out_of_envelope` / `stagnation_flags`) and the
   "box→driver is a *ranker*" framing from `box_driver_calibration`
   are the honest, evidence-backed posture. Do **not** ship or report
   forward-model magnitude in the calm-night regime.
2. **Magnitude is a separate nowcast product.** If extreme-magnitude
   prediction is required, scope a **persistence/nowcast** component
   fed by recent *observed* H2S (or a real-time upstream sensor) —
   explicitly not the box/driver, with realistic expectations
   (recall ≈ 0.2, precision ≈ 0.35 at the autoregressive ceiling with
   this data). This is a product/data decision, not a calibration.
3. **The binding constraint is data, not modelling.** Reinforces the
   calm-night-reanalysis recommendation: closing the gap needs *new*
   real-time/independent data (anemometer, upstream H2S), not more
   modelling of `modeldata_h2s_nofill`. Stop calibrating the forward
   model against Berry's extremes — that line is exhausted.

## Limitations

- Single receptor (Berry), by design (the question is Berry's
  extremes). Chronological split; the negative is on *both* the
  baseline and every exogenous config, so not a split artefact.
- Trigger family is single-feature threshold × boost. A learned
  multi-feature event classifier was deliberately not built: it would
  re-derive attribution's result (exogenous features < 0.11) with
  more degrees of freedom and worse honesty. The autoregressive
  ceiling shows where the recoverable signal actually lives.
- The autoregressive number is a *reference ceiling*, not a proposed
  model here — a real nowcast needs its own experiment + leakage-safe
  evaluation (lagged, gap-aware) before any claim.

## Files

- `output/summary.json` — baseline / best-exogenous / autoregressive
  per regime, all classification + rank metrics.
