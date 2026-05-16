# Emission-driver attribution for Berry's calm-night extremes

**Date:** 2026-05-15
**Status:** done — **positive, with a sharp negative sub-finding**
**Author:** autonomous (Claude Code session)
**Follows:** `2026-05-15_box_calibration` (proved the constant box is necessary-not-sufficient)

## Question

The box calibration showed the residual at Berry is *emission-driven*
(constant-box held-out rank-skill ceiling: Spearman 0.127 operational /
0.218 `stable_atm`). Before designing a time-varying `E_local(t)`:
**which exogenous drivers actually carry that variance, and does the
emissions form we already ship capture it?**

## Approach

Held-out (chronological 70/30, same split as the calibration run, so
numbers compare directly). Three tests on Berry stagnation hours:

1. Per-driver Spearman vs observed H2S — **exogenous** drivers (usable
   in a forward emissions model) vs **autoregressive** (`h2s_lag*` /
   `h2s_rolling*`, reported *reference-only*, never usable as a
   driver, to bound how predictable these hours are at all).
2. The shipped `tijuana_dispersion.emissions` multiplicative form,
   **unfitted** (literature `EmissionParameters`).
3. A fitted non-negative least-squares blend of the top-6 exogenous
   drivers as a loose upper bound.

The bar for every number: the constant-box ceiling **0.127 / 0.218**.

## Headline

- **Temperature is the driver.** `temperature_2m` alone reaches
  held-out Spearman **0.33** on Berry stagnation hours — ~2.5× the
  operational ceiling, ~1.5× the `stable_atm` ceiling. A
  temperature-led `E_local(t)` clears the bar; nothing else
  single-handedly does.
- **The shipped emissions form FAILS this regime, unfitted: 0.02
  (operational) / −0.11 (`stable_atm`).** Its `f_volatilization ∝
  wind²` term *suppresses* emissions exactly on the calm nights when
  the extremes occur. The box's `E_local(t)` must **not** reuse the
  wind-quadratic volatilization factor; a naive `emissions.py`
  plug-in would actively hurt.
- **Parsimony wins.** A non-negative multivariable blend (0.16 / −0.24)
  does *worse* than the single temperature driver — design a small,
  physically-interpretable temperature-led term, not a regression.
- **Autoregressive reference:** `h2s_lag_1h ≈ 0.70`. Strong
  hour-to-hour persistence — the physical analogue of the box's
  accumulation memory. The box supplies persistence *endogenously*;
  the driver only has to select *which* warm/loaded nights. Realistic
  target for the driven box ≈ 0.3–0.5 Spearman, not 0.7.

See RESULTS.md. Feeds the service-repo emission-driver design issue.

## Reproduce

```bash
uv pip install -e ../tijuana-dispersion
uv run python experiments/2026-05-15_emission_driver_attribution/run.py
```
