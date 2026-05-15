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

## Receptor identity (corrected 2026-05-15)

**`NESTOR - BES` IS Berry Elementary School** (BES), in the Nestor
neighborhood of San Diego — confirmed by the project owner. An earlier
draft wrongly concluded "Berry is not in our data" after a substring
search; in fact Berry is one of our three core monitors. The
substring `berry` in `complaints.parquet` ("Mul**berry** Dr", San
Marcos, lat 33.14) is an unrelated false match and is *not* what the
user meant. Receptor map:

- `NESTOR - BES` → **Berry Elementary School** (Nestor, San Diego)
- `SAN YSIDRO`   → San Ysidro monitor
- `IB CIVIC CTR` → Imperial Beach Civic Center

The May 10–11 event analysed here is therefore **exactly** the Berry
Elementary event the user reported. Findings apply directly.

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
