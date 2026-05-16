# Stagnation-box calibration vs Berry's >100 ppb hours

**Date:** 2026-05-15
**Status:** done — **negative result** (box is necessary, not sufficient)
**Author:** autonomous (Claude Code session)
**Follows:** service issue #3 (shipped, uncalibrated), `2026-05-15_calm_night_wind_reanalysis`, `calibration_v3_6_mixing_lid`

## Question

Service issue #3 shipped the calm-night accumulation box
(`tijuana_dispersion.stagnation.box_series`) + per-timestep regime
dispatch, with deliberately **uncalibrated** physical defaults (no
calibration data lives in the service repo). Does *calibrating* it
against the 242 Berry (NESTOR - BES) >100 ppb hours give the
calm-night regime real skill?

## Approach

`box_series` (the shipped recurrence) driven by the actual Berry met
over the full hourly series. Identifiability is explicit: amplitude
is governed only by the lumped group `E_local / (A·H_mix)`, so the
H_mix table and area `A` are held at the shipped physical defaults,
the single amplitude `E_local` is fit in closed form (the box is
linear in it), and `τ` is fit on a grid (it is identifiable through
the *dynamics*, not the level).

Honesty controls: chronological **70/30 train/test** split (all skill
on held-out data); **Spearman** headline (repo convention on
heavy-tailed H2S); an amplitude-invariant **rank-skill ceiling** (best
Spearman any (τ, E_local) in the box family can reach — cannot be
gamed by the fit objective); both the operational `is_stagnation`
classifier and the reanalysis-preferred `stable_atm` reported;
"before" = the pure-Gaussian Berry prediction via the shipped service
path with dispatch off, on the canonical May 10–11 event.

## Reproduce

The pinned `tijuana-dispersion @ v0.3.0` extra **predates** the box
(it is on service `main`, issue #3 merge). Locally:

```bash
uv pip install -e ../tijuana-dispersion
uv run python experiments/2026-05-15_box_calibration/run.py
```

Bumping the experiments-repo pin to a release tag that includes the
box is a PR-gated follow-up (flagged in RESULTS.md, not done here).

## Headline

Calibration does **not** rescue the regime. The box removes the
*geometric* Gaussian failure (event peak 0.16 → 7.9 ppb) and is
weakly directionally correct, but its held-out rank-skill **ceiling**
on Berry stagnation hours is only Spearman ≈ 0.13 (operational) /
0.22 (`stable_atm`), it lifts **0 %** of held-out >100 ppb hours above
100, and `τ` pegs at the grid maximum. A constant lumped emission
cannot serve both the ~1–10 ppb calm bulk and the 100–750 ppb spikes:
the residual variance at Berry is **emission-driven**, not
ventilation-driven. This closes the "bare box" line the way v3.6
closed the advective line, and points squarely at the next component:
an emission-driver term. See RESULTS.md.
