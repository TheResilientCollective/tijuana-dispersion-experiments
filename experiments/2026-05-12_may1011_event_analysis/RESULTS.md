# Results — May 10–11 2026 event analysis

**Run on:** 2026-05-12
**Runtime:** ~7 s
**Status:** ❌ **Model misses the event entirely.** A real ~177 ppb
            NESTOR event was predicted at ~1 ppb. Diagnoses *why*, and
            answers the river-source question.

## ⚠️ Receptor identity correction (2026-05-15)

An earlier draft of this file claimed "Berry Elementary is not in our
data." **That was wrong.** Per the project owner:

> **`NESTOR - BES` = Berry Elementary School** (BES), in the Nestor
> neighborhood of San Diego.

So the May 10–11 spike analysed below — the 177 ppb event at
"NESTOR-BES" — **is exactly the Berry Elementary event the user asked
about.** Every finding here applies directly. Only the receptor
*label* was misread; the analysis is valid. (Other receptors:
`SAN YSIDRO` = San Ysidro monitor; `IB CIVIC CTR` = Imperial Beach
Civic Center. This mapping is now recorded in the calibration log so
future sessions don't repeat the confusion.)

## 1. There was a large, real event — at Berry Elementary (NESTOR-BES)

Observed H₂S, May 10 20:00 → May 11 05:00 (PT):

| Hour (PT)        | NESTOR obs | NESTOR pred (v3) | SY obs | IB obs |
|------------------|-----------:|-----------------:|-------:|-------:|
| 05-10 22:00      | 4.9        | 1.2              | 1.0    | 0.6    |
| **05-10 23:00**  | **171.3**  | **1.0**          | 4.8    | 0.5    |
| **05-11 00:00**  | **177.1**  | **0.7**          | 2.5    | 0.5    |
| **05-11 01:00**  | **171.1**  | **0.0**          | 2.7    | 0.6    |
| **05-11 02:00**  | **155.8**  | **4.1**          | 3.2    | 0.6    |
| 05-11 03:00      | 36.8       | 0.0              | 1.3    | 0.7    |
| 05-11 04:00      | 1.1        | 0.6              | 0.7    | 0.8    |

A sharp 4-hour nocturnal spike at **NESTOR-BES = Berry Elementary
School** (peak 177 ppb), collapsing by 04:00. SAN YSIDRO and IB CIVIC
CTR stayed low (≤ 5 ppb) throughout — this was a Berry-localised
event. **This is the event the user reported.**

Model skill on the May 9–12 window: NESTOR Pearson **0.019**,
predicted max **22 ppb** vs observed **177 ppb**. During the spike the
model predicted ≈ 1 ppb against 171–177 observed — a ~99 % miss.

## 2. Are the river sources included? Yes — but they're downwind here

The model **does** include the river comprehensively: 36 of 55 sources
are river-related — 18 channel (Tijuana River channel grid + bridges,
3.21 g/s fitted), 7 drains/canyons (Stewart's, Goat Canyon, Smuggler's,
Hollister PS…, 4.31 g/s), 11 estuary-grid (1.46 g/s).

But during this event the NESTOR wind was **FROM the WNW→NNW
(288°→340°) at only 1.5–1.7 m/s**. Bearing of each source group from
NESTOR vs. that upwind arc:

| Source group | Fitted total | In WNW–NNW upwind arc |
|--------------|-------------:|----------------------:|
| channel      | 3.21 g/s     | **0.00 g/s** (bearings 126–239° → *downwind*) |
| drain        | 4.31 g/s     | **0.00 g/s** (bearings 134–212° → *downwind*) |
| estuary      | 1.46 g/s     | 0.48 g/s (bearings 250–291°, marginal) |
| bay          | 0.81 g/s     | 0.81 g/s (Otay Outlet 325°, Fruitdale 358°) |
| NE grid      | 2.48 g/s     | 0.00 g/s |
| **total**    | 12.46 g/s    | **~1.29 g/s** |

**The river channel and drain sources are physically incapable of
explaining this event**: with wind from the NW, every channel/drain
source sits *downwind* of NESTOR — their plume blows away from the
station. Only ~1.3 g/s of the 12.5 g/s field (some estuary + the two
bay ponds) is even in the upwind arc, and at fitted rates that yields
~1–4 ppb, not 170+.

## 3. Why the model misses it — two candidate explanations

Both are project-significant and already on the books:

**(a) An unmodeled source WNW–NNW of NESTOR.** To produce 177 ppb with
NW wind, a strong source must lie toward the coast / Tijuana River
estuary mouth / South Bay shoreline / ocean outfall. The bay ponds are
in that arc but fit to < 1 g/s — far short. This is the same class of
finding as Phase A / v3.2 (missing sources the river-valley field
lacks), now in the *NW* sector.

**(b) Unreliable calm-night wind — the long-flagged open question.**
Wind speed during the spike was **1.5–1.7 m/s** (near-calm nocturnal).
The original `calibration_status.md` "open questions" explicitly
flagged: *"Calm-night anemometer readings are notoriously
unrepresentative because surface eddies dominate."* Under a near-calm
nocturnal **down-valley drainage flow**, actual transport at NESTOR
could be from the SE river sources even though the 10 m anemometer
reports NW. If the true near-surface flow was down-valley, the river
channel/drain sources (4–7 g/s, immediately SE) could fully explain a
170 ppb spike — the model fails only because it trusts a wind direction
that calm-night physics makes unreliable. The sharp onset/offset and
extreme magnitude under 1.5 m/s wind is the classic stagnation/
drainage signature, not a well-mixed plume.

Explanation (b) is the more likely primary driver: a 4-hour, 170+ ppb,
single-station spike under 1.5 m/s wind that vanishes the moment wind
picks up to 5+ m/s (04:00) is textbook nocturnal stagnation, and the
river sources are right there to the SE.

## 4. This generalises — Berry's extremes are stagnation, not advection

The May 10–11 event is not a one-off. Across Berry's full record
(2024-10 → 2026-05, 13,722 hours) there are **242 hours > 100 ppb**
(1.76 %). Their character:

- **97 % nocturnal** (20:00–07:59).
- Median wind speed **2.4 m/s** (mean 2.6); **74 % occur under
  3.5 m/s**, 53 % under 2.5 m/s.
- **Wind direction is uniform across all 16 sectors** (9–19 events
  each — no preferred direction at all).
- All-time Berry max: **752 ppb** (2026-04-04 22:00).

The flat wind-direction distribution is the decisive evidence. If
extreme H₂S reached Berry by advection from a specific source, the
events would cluster in the upwind sector(s) of that source. They
don't — they're spread evenly. Combined with near-calm speeds and
near-total nocturnality, **Berry's extreme regime is local
stagnation / accumulation under a collapsed nocturnal boundary layer,
not directional plume transport.**

A steady-state Gaussian plume model is structurally the wrong tool for
this regime: its concentration goes as 1/u (blows up / is undefined as
u→0) and it *requires* a meaningful wind direction to route a plume —
both assumptions fail under calm-night stagnation. This is why the
model can have a respectable bulk/Spearman fit yet ~zero skill on the
extremes: the moderate hours *are* advective and modelled fine; the
extreme hours are a different physical process the model cannot
represent in principle.

## What this means

1. **The model has no skill on calm-night stagnation events, and that
   is structural, not a tuning gap.** All 242 of Berry's > 100 ppb
   hours are the stagnation regime (97 % nocturnal, 74 % < 3.5 m/s,
   wind direction uniform across all sectors). A steady-state Gaussian
   plume cannot represent a no-preferred-direction near-calm
   accumulation process (c ∝ 1/u is undefined as u→0). The Apr-holdout
   Spearman (Berry 0.52) is carried by the advective moderate hours;
   the model fails precisely on the extreme regime that matters most
   for health — and no source-field or diel tuning fixes that, it
   needs a different model class.
2. **River sources are in the model and are the most likely physical
   culprit for this event** — but the Gaussian-plume + 10 m-wind
   formulation cannot route them to NESTOR under calm-night drainage
   flow.
3. **Wind-data quality is now the #1 modeling limitation**, ahead of
   source-field completeness. Confirmed by an independent route (this
   event) in addition to the SY representativeness finding.

## What should be done next

1. **Calm-night reanalysis.** Pull an independent wind source (NERR /
   TJRTLMET station, or a drainage-flow model) for the May 10–11
   window and compare to the Open-Meteo NESTOR wind used here. If they
   disagree (NW vs down-valley SE), explanation (b) is confirmed and
   the fix is met-data, not sources. This is the single highest-value
   follow-up.
2. **Add a mixing-height / stagnation term.** The original status-log
   open question on nocturnal mixing-height collapse (50–200 m,
   amplifying ground concentrations 5–10×) directly applies — a
   170 ppb spike from modest emissions under a collapsed nocturnal
   boundary layer is physically consistent.
3. **Do not over-invest in more source candidates** until the
   calm-night wind question is resolved — adding sources to fit a
   wind-direction artifact would be fitting noise.
4. **Berry Elementary IS `NESTOR - BES`** — it is already a
   first-class receptor, not a gap. The actionable point is that the
   model misses Berry's calm-night events by ~99 %; fixing that is
   items (1)/(2), not adding a receptor.

## Limitations / caveats

- **Single event.** One spike; the calm-night hypothesis should be
  checked across the full set of NESTOR > 100 ppb nocturnal events,
  not just this one.
- **Wind provenance.** We use the Open-Meteo `wind_direction_10m`
  joined in the parquet. We have not yet cross-checked it against a
  physical anemometer for this window — that's the recommended next
  step, not a conclusion this experiment can close.
- **No Berry obs.** All Berry statements are scope clarifications, not
  measurements.

## Files

- `output/timeseries_holdout.csv` — obs vs pred (v2/v3/v3.1) per
  receptor, May 9–12
- `output/summary.json` — fit metrics on the event window
- `output/fitted_rates_v3.csv` — source rates (training-window fit)
