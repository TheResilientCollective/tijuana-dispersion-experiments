# May 10–11 2026 event analysis

**Date:** 2026-05-12 (analysis); event: 2026-05-10 → 05-11
**Status:** done
**Author:** autonomous (Claude Code session)
**Trigger:** user report that "Berry Elementary levels were high May 10–11";
question of whether predictions capture it and whether river sources
are included.

## Question

1. Did high H₂S occur May 10–11, and how does our best model predict it?
2. Are the Tijuana River sources in the model, and could they explain
   the event?
3. (User-named) "Berry Elementary" — can we evaluate predictions there?

## Important data-scope finding

**"Berry Elementary" is not in any of our data.** The H₂S parquet has
exactly three monitoring sites — IB CIVIC CTR, NESTOR-BES, SAN YSIDRO —
and Berry is not in `sensors.json`. The only "berry" strings in
`complaints.parquet` are "Mul**berry** Dr" in San Marcos (lat 33.14,
~65 km north — unrelated false matches). So we have **no observations
at Berry Elementary** and cannot directly score predictions there. We
*can* report the event at the three real stations, and could add a
virtual Berry receptor if its coordinates are supplied (caveat: see
RESULTS — the model misses this event by ~99% even where we *do* have
obs, so a Berry prediction would be unreliable anyway).

## Approach

Reuse the current best model (v3.5 source field: 55 sources incl. 36
river — 18 channel + 7 drain + 11 estuary — plus NE grid, bay,
sy_nearfield; single-amp diel). Train on the standard Feb 1 – Mar 31
window; "holdout" = May 9–12 2026 (the event). Then compute the
bearing of every source from NESTOR and intersect with the observed
wind during the spike to test whether the river sources are even
geometrically capable of producing the event.

## How to reproduce

```bash
uv sync --extra dev --extra service
python scripts/fetch_data.py --only modeldata_h2s_nofill
cd experiments/2026-05-12_may1011_event_analysis
uv run python run.py
```

See RESULTS.md for the verdict (model misses the event entirely;
river sources are included but geometrically downwind during it;
points to either an unmodeled WNW–NNW source or unreliable calm-night
wind).
