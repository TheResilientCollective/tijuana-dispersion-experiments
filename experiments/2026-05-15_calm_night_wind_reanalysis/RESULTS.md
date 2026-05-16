# Results — calm-night wind reanalysis

**Run on:** 2026-05-15
**Runtime:** < 2 s (no fitting)
**Status:** ✅ Evidence supports explanation **(b)** (calm-night wind
            direction unreliable). ⚠️ Cannot *positively* confirm
            (a) vs (b) without an external anemometer. 🎯 Surfaces an
            immediately-usable stagnation classifier already in the data.

## Data-availability finding (important, slightly negative)

There is **no independent wind source** in the pipeline. `data/manifest.yaml`
ships only the Open-Meteo product; the second met file
(`modeldata_forecast_15min`) was fetched as a **corrupt non-parquet**
(invalid magic bytes — likely an HTML/CSV fallback saved with a
`.parquet` extension). So the status-log plan ("pull NERR/TJRTLMET")
**cannot be executed with current data**. This is itself an
actionable gap (see "Next").

## The five checks

| # | Check | Result | Reading |
|---|-------|--------|---------|
| 1 | `stable_atm` flag vs Berry >100 ppb | **88%** flagged vs **33%** baseline | dataset already identifies the regime |
| 2 | Wind-dir rotation through the spike | **~68°** across the 4 >100 ppb hrs; **~115°** across 20:00–05:00 | vane chasing eddies, not advection |
| 3 | Hour-to-hour \|Δdir\|: calm-night vs windy | **28.9°** vs **6.8°** | direction **4× noisier** when calm-night |
| 4 | SY vs NESTOR Open-Meteo dir (event) | mean **21°**, **max 52°** (4 km apart) | gridded field spatially incoherent at night |
| 5 | Gust/mean ratio: >100 ppb vs baseline | **2.79** vs **2.88** | **non-discriminating** (honest null) |

### The May 10-11 wind, hour by hour

```
23:00  171 ppb  1.7 m/s  288°  stable_atm=1
00:00  177 ppb  1.7 m/s  319°  stable_atm=1
01:00  171 ppb  1.5 m/s  339°  stable_atm=1
02:00  156 ppb  2.5 m/s  356°  stable_atm=1
03:00   37 ppb  3.7 m/s   14°  stable_atm=1
04:00    1 ppb  5.7 m/s   28°  stable_atm=0   <- ventilation returns
```

Direction rotates monotonically clockwise ~68° across the four
>100 ppb hours while speed sits at 1.5–2.5 m/s; the event ends the
hour speed returns to ~5.7 m/s and `stable_atm` flips to 0. This is
the textbook decoupled-nocturnal-surface-layer signature, not a
coherent synoptic plume.

## What this means

1. **Explanation (b) is well-supported.** The model's "river sources
   are downwind of Berry → predict ≈0" conclusion (from the event
   analysis) rests on a wind *direction* that, in exactly these hours,
   is: flagged stable by the dataset itself, 4× noisier than in
   well-ventilated conditions, rotating ~68° in four hours, and
   disagreeing with the SY grid point by up to 52°. There is no basis
   to trust that direction for plume routing. The model failure is at
   least partly a **met-input** failure, not purely a missing source.

2. **Cannot fully close (a) vs (b).** None of these checks *positively*
   demonstrate that the SE river sources caused the event — they
   demonstrate the wind input is unreliable, which removes the
   evidentiary basis for *excluding* them. Positive confirmation needs
   an independent anemometer or a drainage-flow model. Stated plainly
   so this isn't over-claimed.

3. **A stagnation classifier already exists in the data.** `stable_atm`
   marks 88% of Berry's 242 >100 ppb hours (vs 33% baseline) and every
   May 10-11 spike hour. This is materially better than the raw
   `is_night & wind<2.5` heuristic in the service-repo #2 guardrail PR
   and the #3 box-model dispatch design. **Recommend both use
   `stable_atm` (or fold it in) as the regime signal.**

4. **The gust-ratio idea was wrong** (2.79 vs 2.88). Recorded so it
   isn't retried.

## Next

1. **Add an independent anemometer to `data/manifest.yaml`** (NERR
   TJRTLMET, or San Diego APCD met). This is the only way to positively
   confirm (a) vs (b) and to re-route the calm-night plume correctly.
   Also fix/replace the corrupt `modeldata_forecast_15min` source. (Both
   are `data/manifest.yaml` edits → PR-gated per AGENTS.md; flagged, not
   done here.)
2. **Service repo:** update issue #2 (guardrail) and #3 (`stagnation_box`)
   to key off `stable_atm` rather than a raw wind threshold. Comment
   added to those issues recommended.
3. Down-weight / ignore wind *direction* when `stable_atm=1` &
   speed < ~2.5 m/s in any advective routing.

## Limitations

- Internal-consistency only — no ground-truth anemometer. The verdict
  is "wind input unreliable" (well-supported), **not** "river sources
  confirmed" (not shown here).
- `stable_atm` provenance is the upstream Open-Meteo-derived pipeline;
  88% precision on >100 ppb is strong but its own derivation should be
  reviewed before it's hard-wired into a safety guardrail.
- Single event examined in detail; the aggregate stats (242 hours, 4×
  noise ratio) generalise the conclusion beyond the one night.

## Files

- `output/summary.json` — all five metrics + verdict
- `output/event_wind.csv` — the hour-by-hour May 10-11 wind table
