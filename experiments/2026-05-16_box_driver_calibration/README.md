# Box + temperature-led driver calibration (the decisive test)

**Date:** 2026-05-16
**Status:** done — **qualified positive**: clears the rank-skill
ceiling (~2×), magnitude miss persists
**Author:** autonomous (Claude Code session)
**Follows:** `2026-05-15_box_calibration`, `2026-05-15_emission_driver_attribution`; service issue #6 (shipped v0.4.0)

## Question

The constant box was necessary-not-sufficient (held-out rank-skill
ceiling Spearman 0.127 operational / 0.218 `stable_atm`); attribution
showed `temperature_2m` alone → ~0.33. Service #6 shipped a
temperature-led `E_local(t) = E0·Q10^((T−T_ref)/10)` for the box.
**Does the calibrated box→driver line clear the constant-box ceiling
on held-out Berry stagnation hours?**

## Approach

The *shipped* v0.4.0 model (`box_series` + `temperature_led_e_local`),
chronological 70/30 — the identical split to the two prior
experiments, so every number is directly comparable. Identifiability
is stated, not hidden: the box is linear in `E0` (closed-form
amplitude); `T_ref` is fully absorbed into `E0` (non-identifiable from
one receptor → fixed at the shipped 20 °C); `area`/`H_mix` held at
shipped defaults. Only **Q10** (temperature-response shape) and **τ**
(dynamics) move held-out *rank* skill, so the decisive statistic is
the amplitude-invariant **rank-skill ceiling** = best held-out
Spearman over the Q10×τ grid (cannot be gamed by the fit objective),
exactly as in `box_calibration`.

## Reproduce

```bash
uv run python experiments/2026-05-16_box_driver_calibration/run.py
```
Service pinned at **v0.4.0** (first tag with #3 box + #6 driver).

## Headline

The temperature-led driver **delivers what attribution predicted**:
held-out rank-skill ceiling rises to **0.27** (operational) / **0.34**
(`stable_atm`) — clearing the constant-box ceiling by **+0.14 / +0.12**
(roughly **double**), landing at the floor of the 0.3–0.5 design
target and matching the ~0.33 temperature upper bound. **But the
magnitude problem is unsolved**: recall@100 = **0.00**, median
predicted at the >100 ppb hours ≈ 9–10 ppb vs observed ≈ 167–177 ppb,
May 10-11 event peak 7.7 ppb vs 177. The box→driver is validated as a
**relative calm-night severity ranker**, *not* an absolute-ppb
predictor in the extreme regime. See RESULTS.md.
