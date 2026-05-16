# Calm-night wind reanalysis

**Date:** 2026-05-15
**Status:** done (no-fitting diagnostic)
**Author:** autonomous (Claude Code session)
**Follows:** `may1011_event_analysis`, `calibration_v3.6`

## Question

The Berry May 10-11 analysis left two explanations for the model's
~99% miss on Berry's nocturnal extremes:

- **(a)** an unmodelled source WNW-NNW of Berry, or
- **(b)** the calm-night Open-Meteo wind direction is unreliable, so
  the model routes the (real, SE) river-source plume the wrong way.

The status log flagged "pull an independent anemometer
(NERR/TJRTLMET)" as the way to decide. **There is no such independent
feed in our data pipeline** (`data/manifest.yaml` ships only the
Open-Meteo product; `modeldata_forecast_15min` fetched as a corrupt
non-parquet). So this experiment runs the strongest
internal-consistency + physical-plausibility reanalysis the available
data supports, and is explicit about what it cannot close without
external met.

## Approach

Five checks on the committed `modeldata_h2s_nofill` parquet (no
fitting): the dataset's own `stable_atm` flag vs Berry's >100 ppb
hours; wind-direction rotation through the May 10-11 spike;
hour-to-hour direction instability (calm-night vs windy); SY-local vs
NESTOR Open-Meteo spatial coherence during the event; gust/mean ratio.
See `run.py`; outputs in `output/` (gitignored).

## Reproduce

```bash
uv run python experiments/2026-05-15_calm_night_wind_reanalysis/run.py
```

## Headline

Evidence supports **(b)** — the calm-night wind direction is
unreliable for plume routing — and, importantly, surfaces a
ready-made stagnation classifier (`stable_atm`) already in the data.
A true external anemometer is still required to *positively* confirm
(a) vs (b). See RESULTS.md.
