# Results — emission-driver attribution for Berry's calm-night extremes

**Run on:** 2026-05-15
**Runtime:** ~25 s
**Status:** ✅ Positive — a temperature-led `E_local(t)` clears the
constant-box ceiling. ⚠️ Sharp negative sub-finding: the shipped
`emissions.py` form, unfitted, *fails* this regime (wind-quadratic
volatilization suppresses calm-night emissions). 🎯 Gives the
service-repo emission-driver design its functional form and guardrails.

## Setup

12 964 Berry (NESTOR - BES) hours, 242 > 100 ppb. Held-out
chronological 70/30, identical split to `2026-05-15_box_calibration`,
so every number compares directly to the constant-box rank-skill
ceiling: **0.127** (operational `is_stagnation`) / **0.218**
(`stable_atm`).

## Held-out Spearman vs Berry stagnation-hour H2S

### Exogenous drivers (usable in a forward emissions model)

| Driver | `is_stagnation` | `stable_atm` |
|---|--:|--:|
| **temperature_2m** | **0.326** | **0.335** |
| surface_pressure | −0.209 | −0.235 |
| precipitation | −0.175 | −0.169 |
| tide_height | 0.157 | 0.050 |
| sbiwtp_flow_x_temp | 0.107 | 0.094 |
| sbiwtp_flow_mgd | −0.087 | −0.110 |
| flow_log / Border flow | 0.083 | 0.009 |
| sbiwtp_* (deficit/anom/sli) | <0.06 | <0.06 |

### Reference only — autoregressive, **NOT** a usable driver

| | `is_stagnation` | `stable_atm` |
|---|--:|--:|
| h2s_lag_1h | 0.698 | 0.725 |
| h2s_rolling_6h | 0.699 | 0.733 |
| h2s_rolling_24h | 0.552 | 0.577 |

### Composite forms

| | `is_stagnation` | `stable_atm` | beats ceiling? |
|---|--:|--:|--|
| Constant-box ceiling (prior) | 0.127 | 0.218 | — |
| **Best single exogenous (temperature)** | **0.326** | **0.335** | **yes (2.5× / 1.5×)** |
| Shipped `emissions.py` form, **unfitted** | 0.022 | **−0.114** | **no** |
| Fitted NNLS top-6 (upper bound) | 0.157 | −0.235 | not robustly |

## What this means

1. **Temperature is the lever.** `temperature_2m` alone is a robust,
   monotone, held-out Spearman ≈ 0.33 across *both* regime
   definitions — comfortably above the constant-box ceiling. Physically
   coherent: biogenic H2S production is microbial sulfate reduction,
   Q10-type temperature dependence; warm calm nights → more production
   *and* a shallow trapping box → the extremes. The box already has
   the trapping; the missing piece is the temperature-driven
   production term.

2. **Do NOT plug in the shipped emissions form as-is.** Unfitted it
   scores 0.02 / −0.11 — no skill, *anti*-correlated under
   `stable_atm`. Root cause: `f_volatilization ∝ wind²` (Wanninkhof
   gas-transfer) drives emissions toward zero at low wind — exactly
   the calm-night hours that produce the extremes. The
   air–water-transfer story is fine for advective daytime but is the
   wrong sign for the trapped-box regime. The box's `E_local(t)` must
   use a **temperature-led production term and exclude the
   wind-quadratic volatilization factor**.

3. **Be parsimonious.** The non-negative multivariable blend is *worse*
   than the single temperature driver (0.16 / −0.24). (The −0.24 is
   partly an estimator artifact: nonneg-NNLS on signed standardized
   features is ill-posed — recorded as a method caveat, not a model
   result. The robust conclusion is: a small temperature-led form, not
   a regression.)

4. **Ceiling vs target.** Autoregressive `h2s_lag_1h ≈ 0.70` bounds
   how predictable these hours are; exogenous drivers cap ≈ 0.33. The
   gap is the persistence the **box accumulation supplies
   endogenously** (its memory term is the physical analogue of
   `h2s_lag`). So the realistic target for the *driven box* (driver
   selects the night, box integrates it) is ≈ **0.3–0.5** Spearman on
   held-out Berry stagnation hours — not 0.7, and not 0.13.

## Recommended design (feeds the service-repo issue)

Make the box's `E_local` time-varying via the existing
`EmissionsModel` / `EmissionDrivers` plumbing, but with a
**calm-night production form**:

```
E_local(t) = E0 · Q10^((T(t) − T_ref)/10) · f_substrate(t)        [optional]
             # NO wind-quadratic volatilization in the box path
```

- `Q10`, `T_ref`, `E0` calibrated in the experiments repo (this repo
  has the data; the service ships uncalibrated defaults — same
  contract as issue #3).
- `f_substrate` (flow/SBIWTP) is *optional and secondary* — its solo
  skill is < 0.11; include only if it improves held-out skill in
  calibration, else drop for parsimony.
- Box accumulation unchanged; only `e_local_g_s` becomes a
  per-timestep series fed from `EmissionsModel`.

**Acceptance bar** for the service issue: held-out Berry
stagnation-hour Spearman must clear the constant-box ceiling
(0.127 / 0.218); design target 0.3–0.5. Validated in a paired
experiments-repo calibration (not in the service repo).

## Next

1. Service-repo issue: *time-varying `E_local(t)` for the stagnation
   box* — temperature-led, wind-quadratic-volatilization excluded,
   interface = box pulls `E_local(t)` from `EmissionsModel`. Drafted
   from this evidence.
2. Experiments-repo follow-up (after the service interface lands):
   calibrate `Q10`, `T_ref`, `E0` (+ optional substrate) on the box
   path; report held-out skill vs the 0.127/0.218 ceiling.
3. Pin bump still pending (PR-gated; carried from `box_calibration`).

## Limitations

- Single receptor (Berry) by design — the question was Berry's
  extremes specifically.
- Per-driver Spearman is univariate; interactions (e.g.
  temperature × substrate) not exhaustively searched — deliberately,
  to keep the design parsimonious. Calibration can test one
  interaction term and keep it only if held-out skill improves.
- `temperature_2m` is itself diurnally correlated; some of its skill
  overlaps the box's stability/diel structure. The box-path
  calibration (next) controls for this because the box already
  consumes stability — so the temperature term is fit *given* the
  box, isolating its incremental contribution.

## Files

- `output/summary.json` — all per-driver + composite metrics, both regimes
