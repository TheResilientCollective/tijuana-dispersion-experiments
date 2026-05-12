# Results — SY north-residual diagnostic

**Run on:** 2026-05-11
**Runtime:** < 2 s
**Outputs:** `output/sector_means.csv`, `output/elevated_sy_north.csv`,
            `output/nestor_heavy_events.csv`, `output/v3_rates_at_bound.csv`,
            `output/summary.json` (all gitignored)

## Question

Where does the un-modeled SAN YSIDRO N/NE residual (flagged in
[calibration v3 RESULTS](../2026-05-11_calibration_v3/RESULTS.md))
come from, and which fix should the next experiment try?

## What we did

Pure data analysis on the Apr 1-14 holdout window. Three cuts:

1. **Per-sector mean H₂S at all 3 receptors** using NESTOR's wind
   direction as the canonical met.
2. **NESTOR-heavy events** (NESTOR > 50 ppb): which sectors and hours?
3. **v3 fitted-rate inspection**: which sources hit their archetype cap?

## Key findings

### Finding 1 — SAN YSIDRO is *uniquely* elevated in the N sector

Per-sector mean H₂S (ppb) on holdout:

| Sector | SAN YSIDRO | NESTOR-BES | IB CIVIC CTR | n hours |
|--------|-----------:|-----------:|-------------:|--------:|
| **N**  | **30.3**   | 13.4       | 1.4          | 9       |
| NNE    | 10.0       | 96.6       | 0.8          | 7       |
| NE     | 7.6        | 50.5       | 4.2          | 13      |
| ENE    | 6.2        | 47.7       | 3.1          | 13      |
| E      | 6.0        | 16.3       | 5.4          | 14      |
| ESE    | 2.7        | 34.2       | 12.4         | 13      |
| SE     | 4.5        | 95.3       | 38.8         | 20      |
| W      | 5.6        | 12.3       | 1.1          | 61      |
| **NNW**| **29.3**   | 83.2       | 0.9          | 7       |

In every other sector NESTOR > SAN YSIDRO. **In the N and NW sectors,
SAN YSIDRO is uniquely elevated** (30 ppb mean), while NESTOR is lower
and IB sees essentially nothing. That's a geometric signature that
cannot come from any of the modelled sources (all of which are *west*
of SAN YSIDRO, in the river valley) — it requires a source *north or
northeast of SAN YSIDRO*.

### Finding 2 — NESTOR's N/NE peaks are large and nocturnal

19 hours in the holdout have SY > 10 ppb under N/NE/ENE/E winds; mean
SY in those 19 hours is **27 ppb**. During those same hours, NESTOR
often shows much higher H₂S (one hour at 294 ppb, several at 100-200
ppb). NESTOR > 50 ppb occurs in 54 holdout hours total; **all are
nocturnal (20:00 – 07:59)**.

This is consistent with two source regimes operating during N/NE wind:
- one *between* NESTOR and SAN YSIDRO (visible at both, peaking at NESTOR)
- one *east or northeast of SAN YSIDRO specifically* (visible at SY in
  N/NNW sectors, mostly invisible at NESTOR — the SY-only fingerprint
  in Finding 1)

### Finding 3 — the bay archetype cap is binding in v3

Of 38 sources, exactly one hit its upper bound after v3's fit:

| Source                                | Archetype | Fitted rate (g/s) | Bound |
|---------------------------------------|-----------|------------------:|------:|
| San Diego Bay ponds Otay River Outlet | bay       | 0.500             | 0.500 |

The second bay source (San Diego Bay Ponds near Fruitdale, 32.595,
-117.092) sits at 0.27 g/s — not at cap. So the *Otay River Outlet*
bay pond at (32.594, -117.114) wanted to absorb more mass and couldn't.

This source is **north of NESTOR** (3 km) and **west of IB** (only 0.6 km),
so its plume reaches NESTOR strongly when wind is from N/NW. It does
*not* reach SAN YSIDRO (4 km east). So while relaxing the bay cap
will help NESTOR's N-wind fit, it won't address the SY-only N residual.

## Numbers (acceptance flags for v3.1 design)

| Question                                            | Answer |
|-----------------------------------------------------|--------|
| Is SAN YSIDRO uniquely elevated in N sector?        | yes (SY 30 ppb vs NESTOR 13 ppb) |
| Hours with N-wind + SY > 10 ppb on holdout          | 19     |
| NESTOR > 50 ppb event hours on holdout              | 54     |
| Fraction of those that are nocturnal (20:00-07:59)   | 100%   |
| Did any v3 source hit its archetype bound?          | yes (1 bay source) |
| Is the binding source the Otay River Outlet bay?    | yes    |

## What this means

The v3 residual at SAN YSIDRO has **two distinct components** with
**two distinct fixes**:

1. **NESTOR-side N/NW residual** — the bay-pond Otay River Outlet
   source is rate-limited by the archetype cap (0.5 g/s). Fix: relax
   bay cap, refit. This should improve NESTOR's N-sector fit
   substantially.

2. **SAN YSIDRO-only N/NE residual** — no existing source is N or NE
   of SY. The signal is geometrically inconsistent with the river-
   valley sources (all west). Fix: add a candidate source east or
   north of SAN YSIDRO. Plausible locations:
   - Otay Mesa industrial area (lat ~32.59, lon ~-117.04)
   - Tijuana cross-border (lat ~32.55, lon ~-117.04, just south of border)
   - Local urban background at SY itself (small ambient)

Both fixes can be applied together in v3.1 / v3.2.

## What should be done next

In priority order — each is its own experiment:

1. **v3.1: per-archetype diel + relaxed bay cap.** The user's
   originally-suggested fix combined with the bay-cap finding from this
   diagnostic. Low risk, fast to run.
2. **v3.2: add a candidate NE/N-of-SY source and refit.** Tests the
   "missing source east of SAN YSIDRO" hypothesis directly. If it
   absorbs significant rate, we have a new source candidate to
   investigate physically.
3. **v3.3: broader outer optimization** (add Q₁₀ and substrate
   parameters). Lower expected value but cheap.

## Limitations / caveats

- **Met is NESTOR-only.** Wind at SAN YSIDRO during N-sector hours
  could differ from NESTOR's. We can't disprove a "local wind is
  actually from W, source is the channel sources" interpretation
  without independent SY-local wind data. The geometric signature
  (SY uniquely elevated) is suggestive but not conclusive.
- **Diagnostic uses Apr 1-14 only.** Training-window patterns
  may differ. v3.1 should re-check on the full train.
- **No statistical test.** N=9 hours in the N sector is small.
  The 30 vs 13 ppb gap could be one or two events. Worth verifying
  with a longer window when one becomes available.
- **No bay archetype was added by v3** (it just hit the existing 0.5
  cap). The fix in v3.1 is mechanical, not adding physics.

## Files

- `output/sector_means.csv` — full 16-sector table of mean H₂S per receptor
- `output/elevated_sy_north.csv` — the 19 specific hours with SY > 10 under N wind
- `output/nestor_heavy_events.csv` — the 54 NESTOR > 50 ppb events
- `output/v3_rates_at_bound.csv` — v3 sources at upper archetype bound (just one)
- `output/summary.json` — machine-readable findings
