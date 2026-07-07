# Self-improving calibration loop — roadmap

**Status:** planning (2026-06-25). Decisions locked via planning session; phases
below are the build order. This doc is the shared spec — the eventual outer
loop reads it, and `calibration_status.md` logs progress against it.

## Vision: two loops and a spine

- **Inner loop (numeric, on NRP).** Sobol / MCMC / CV / (later) HYSPLIT jobs.
  Deterministic, uniquely tagged, reproducible. Already exists in shape
  (`runs/<tag>/`, `sobol_post_analysis`, `compare.py`, the `mcmc_*` scaffold).
- **Outer loop (agentic, "Ralph").** Reads the latest results, proposes the
  next experiment, submits it, scores it out-of-sample, records it, repeats.
- **The spine.** An append-only, conflict-free **run ledger** that indexes
  every run. The outer loop reads it to know "what's been tried / best so far";
  the report site renders it. Everything hangs off this.

## Locked decisions (planning session 2026-06-25)

| Decision | Choice |
|---|---|
| **Objective** | **Walk-forward event skill** — fit on past, predict held-out *future* events, score peak concentration + timing. Requires a frozen test set. |
| **Loop autonomy** | **Start at v1 (local `/loop`, supervised); architect for v3 (autonomous on NRP).** Clean module boundaries make the jump a config change, not a rewrite. |
| **Build first** | **Keystone (manifest + site) + close the MCMC inner loop**, together. |
| **HYSPLIT** | **Off the critical path, but on an isolated parallel track** (own branch/worktree, own code location, own image + `runs/hysplit/` prefix). Surfaces in the shared site; never touches calibration code. |

## The objective: walk-forward event skill (the thing the loop optimizes)

A self-improving loop is only honest if its improvement signal is **out of
sample**. Optimizing on the data you score on "improves" by overfitting.

- **Events.** The labeled spike episodes we already track (Dec 2025 cluster,
  Apr 2026 752 ppb, May 2026 Berry, Feb/Mar baselines, …).
- **Chronological split** (walk-forward, no leakage):
  - **Train** — earliest events; used to fit parameters.
  - **Validation** — middle events; the loop optimizes against this.
  - **Test** — latest events; **frozen**, touched only to *report* final skill
    (and rarely, to detect validation overfitting). Pre-registered, like H1–H6.
- **Per-event skill score** (per receptor, then aggregated):
  - peak-concentration error — log-ratio of predicted vs observed peak ppb
  - peak-timing error — hours between predicted and observed peak
  - combined into one scalar per (event, receptor); weights TBD/tunable.
  - Report as a **skill score** `S = 1 − MSE_model / MSE_reference` against a
    persistence/climatology baseline, so `S > 0` = beats baseline.
- **This scalar is the loop's reward.** Defined once in `nrp/skill.py` as a pure
  function over S3 artifacts so both inner (CV asset) and outer (loop) use it.

## Keystone: conflict-free, typed, browsable run store (Phase 1)

```
s3://tj-calibration/
  runs/{kind}/{tag}/              kind ∈ sobol | mcmc | cv | hysplit
     manifest.json                self-describing record (schema below)
     <artifacts>                  indices.parquet / posterior.nc / conc.nc / …
     summary.md  plots/*.png
  ledger/runs.jsonl               BUILT by listing manifests (not appended live)
  site/ index.html  runs/*.html   generated browse UI
```

**Conflict-free by construction:** parallel jobs never write a shared file.
Each run writes only its own `manifest.json`. A separate `build_index` step
*lists* manifests → assembles `ledger/runs.jsonl` + the site. This sidesteps
the S3-append race that bit the bulk Sobol run (chunk IO keyed by asset).

**`manifest.json` schema (v1):**
```json
{
  "kind": "sobol", "tag": "2026-03-13_2026-03-16_N8192_seed42_2026-06-24",
  "window": ["2026-03-13", "2026-03-16"], "n_base_samples": 8192, "seed": 42,
  "git_sha": "1f241f6", "image_digest": "sha256:…",
  "status": "complete", "created": "2026-06-24T20:31:00Z",
  "skill": {"validation": 0.42, "test": null},
  "headline": {"top_param": "diel_phase_hours", "top_ST": 0.77},
  "artifacts": {"indices": "runs/sobol/<tag>/indices.parquet", "summary": "…/summary.md"}
}
```

**Report site:** `build_report_site` lists manifests → sortable `index.html`
(kind, window, skill, headline, git_sha, date, link) + per-run pages embedding
`summary.md` + plots. **Publish to GitHub Pages** from the experiments repo
(zero cluster ingress, instantly shareable); S3 stays the artifact store.

## Phase plan

### Phase 1 — Keystone (manifest + ledger + site)
- `nrp/runstore.py`: `write_manifest()`, `build_ledger()`, run_tag typing.
- Refactor `sobol_post_analysis` (and the mcmc/cv post-analysis) to write
  `runs/{kind}/{tag}/manifest.json` + artifacts under the typed prefix.
- `build_index` asset/script → `ledger/runs.jsonl` + `site/` (Jinja2).
- GitHub Pages publish (CI job on the experiments repo).
- *Outcome:* every past and future run is visible in one browsable place.

### Phase 2 — Close the MCMC inner loop
- Wire the forward model (`tijuana_dispersion`) + obs loader into `mcmc.py`
  (the current TODOs / random-data placeholders).
- `nrp/skill.py`: the walk-forward skill score (above), with the event split.
- `submit_mcmc.py` (mirrors `submit_sobol.py`): submit a posterior run by spec.
- CV asset evaluates posterior-predictive skill on held-out events.
- *Outcome:* a parameter set in → an out-of-sample skill score out.

### Phase 3 — Outer loop v1 (supervised), built on autonomy-ready interfaces
Five clean modules with stable JSON-spec / S3-tag I/O, so v1→v3 is a config flip:
1. **Proposer** — `(ledger, best) → experiment_spec`. v1: the agent (you + me)
   decides; v3: an autonomous policy emits the same spec.
2. **Submitter** — `experiment_spec → tag` (the `submit_*.py` scripts).
3. **Scorer** — `tag → skill` (pure fn over S3; writes manifest).
4. **Gate** — accept/reject + "does this run need human approval?" (a cost
   threshold). v1: human approves big runs; v3: loop respects the same gate.
5. **Ledger + site** — shared, read-only aggregation.
- v1 driver: a Claude Code `/loop` you supervise. v3 driver: a scheduled/on-NRP
  loop that only gates the largest runs.

### Phase 4 (parallel, isolated) — HYSPLIT spike
- **Isolation:** branch/worktree `feat/hysplit-spike`; a **separate Dagster code
  location** (`hysplit`) in `dagster-user-deployments` with its own image +
  gRPC server (the `nrp` calibration location is untouched by HYSPLIT deploys);
  `runs/hysplit/` prefix; its own worker image tag.
- **Back-trajectories** from each spike → source-region attribution (independent
  cross-check on the emission-inventory forward model). Highest insight/effort.
- **Forward concentration** from candidate sources → an independent prediction
  to ensemble against `tijuana_dispersion`.
- New lift to budget: ARL met data (HRRR high-res / GDAS coverage), a
  containerized HYSPLIT binary (NOAA registration), output adapters mapping
  trajectories/conc-grids onto the 3-receptor metrics.
- Surfaces in the shared site once results exist; code stays isolated.

## Risks / guardrails
- **Overfitting** — the loop *must* score out-of-sample; frozen test set is
  pre-registered and rarely touched. This is the single most important rule.
- **Cost/runaway** — the Gate enforces a per-iteration compute budget and a
  human-approval threshold for large runs (matches the AGENTS.md merge gates).
- **Reproducibility** — every manifest pins `git_sha` + `image_digest`; the
  reaper + persistent DB (already done) keep NRP stable under loop volume.
- **Parallel-track safety** — HYSPLIT's separate code location means a broken
  HYSPLIT deploy can't take down the calibration location.

## Immediate next step
Phase 1 keystone is the unblock. Concretely: `nrp/runstore.py` +
retrofit `sobol_post_analysis` to the typed manifest layout + a first
`build_index`/site pass over the existing archives, so we can *see* what we
already have before wiring the MCMC loop onto it.
