# AGENTS.md — `tijuana-dispersion-experiments` repository

This file is the operating manual for any AI coding agent working in this repository. Read it in full at the start of every session. The rules in this file supersede any contradicting habits or training defaults the agent might have.

## What this repo is

The research workspace for the Tijuana H₂S dispersion project. Calibration runs, sensitivity analyses, emissions-model development, and NRP batch jobs live here. **This repo is messy by design** — exploratory work doesn't fit in a deployment-grade service repo. But it is *reproducibly* messy: every analysis must be re-runnable from the committed code plus the data manifest, and every result that matters has a `RESULTS.md` capturing what we learned.

This repo does **not** contain the dispersion service itself. That lives in `theresilientcollective/tijuana-dispersion`. This repo *uses* the service as a dependency (installed via `uv pip install` from a Git ref).

## Skills installed for this repo

- **`dignified-python@dagster-skills`** — modern Python coding standards. Read at session start.
- **`dagster-expert@dagster-skills`** — Dagster patterns. Read when working in `nrp/` or any `dagster_*.py` file.

## Hard rules (these matter even more here than in the service repo)

### 1. Analyses must be repeatable

Every experiment under `experiments/<date>_<name>/` must include:
- `run.py` (or `run.ipynb`) — the script/notebook that produces the results.
- `RESULTS.md` — a written summary of what was learned, committed to git.
- A header comment in `run.py` listing inputs (data files, parameter sets, code versions) and outputs (artifact paths).

`output/` directories are git-ignored. They are reproducible from `run.py`. If your analysis cannot be re-run from the committed code plus `data/manifest.yaml`, you have not finished.

### 2. No synthetic, mock, or placeholder data outside `tests/`

Same rule as the service repo. Functions in `emissions_research/` and any analysis script must never silently substitute fake data when real data is missing. Raise an exception. Mock data is for unit tests only.

This is the rule most likely to be violated by accident in this repo. A typical bug pattern: an experiment script reads `modeldata_h2s_nofill.parquet`, finds the file is missing, and "helpfully" generates random data so the script doesn't crash. Don't. Fail loudly. Real data missing → exception, full stop.

### 3. No data files in git

Use `data/manifest.yaml` to declare data sources. Run `python scripts/fetch_data.py` to populate `data/raw/` (gitignored). If a new data source is needed, add it to the manifest with URL and (optional) sha256, don't commit the file.

The H₂S parquet from `oss.resilientservice.mooo.com` is the canonical source. Fetch it; don't copy it into the repo.

### 4. Parquet preferred over CSV

When reading: try `.parquet` first, fall back to `.csv` only when parquet doesn't exist. The H₂S parquet uses timezone-aware `datetime64[ns, America/Los_Angeles]` indices natively; CSV requires explicit `pd.to_datetime(..., utc=True).dt.tz_convert('America/Los_Angeles')`. The parquet form is the correct one.

When writing: write parquet for any tabular output that another script will consume. CSV is acceptable for human-readable summaries (e.g., a final results table that goes alongside `RESULTS.md`).

### 5. Notebooks committed without outputs

`nbstripout` is in pre-commit. Notebooks with cell outputs will be auto-stripped on commit. This keeps diffs readable. If a notebook output (figure, table) matters, save it as a file in `output/` and reference it from the markdown.

### 6. No secrets in source

Same as the service repo. `detect-secrets` runs in pre-commit and CI.

## Repository structure

```
tijuana-dispersion-experiments/
├── experiments/                     # one folder per experiment, dated
│   ├── _template/                   # copy this to start a new experiment
│   ├── 2026-05-05_calibration_v2/
│   └── 2026-05-05_sensitivity_lhs/
├── notebooks/                       # exploratory only; promote to experiments/ when done
├── nrp/                             # Dagster pipelines + K8s manifests for NRP
│   ├── dagster_pipeline.py
│   ├── Dockerfile
│   └── k8s/
├── emissions_research/              # the emissions model (pre-stable; will graduate to service repo)
├── data/
│   ├── manifest.yaml                # data source declarations
│   └── raw/                         # gitignored; populated by scripts/fetch_data.py
├── scripts/
│   └── fetch_data.py
├── docs/
│   ├── calibration_status.md        # the running log; update after every calibration run
│   └── nrp_dagster.md               # NRP architecture
└── AGENTS.md                        # this file
```

## Development workflow

### At session start

1. `git pull`.
2. Read `docs/calibration_status.md` to see what was last established about the calibration state.
3. Read this file.
4. Check open issues with `gh issue list`.

### Starting a new experiment

1. Copy `experiments/_template/` to `experiments/<YYYY-MM-DD>_<short_name>/`.
2. Fill in `README.md` with: hypothesis (what question are you answering?), method (what will you do?), expected outputs (what artifacts will you produce?).
3. Implement in `run.py` or `run.ipynb`.
4. After running, write `RESULTS.md`: what happened, what was learned, what's next. Be honest — null results are valuable.
5. Commit on a feature branch, open a PR.

### Running an experiment that touches NRP

1. Check `docs/nrp_dagster.md` for the current Dagster pipeline structure.
2. Use existing Dagster assets where possible. Add new ones under `nrp/dagster_pipeline.py`.
3. Test locally with `dagster dev` before deploying jobs to NRP.
4. Submit jobs only from a branch with green CI.
5. Capture run metadata (Dagster run ID, K8s pod logs) in the experiment's `RESULTS.md` so the result can be traced back to the run.

### PR requirements (laxer than service repo)

Auto-merge is **enabled** for changes that touch only:
- `experiments/**` (any file)
- `notebooks/**` (any file)
- `RESULTS.md` files in any subdirectory

Auto-merge is **disabled** for changes to:
- `pyproject.toml`, `requirements.txt`, lockfiles
- `nrp/Dockerfile`, K8s manifests
- `scripts/fetch_data.py`, `data/manifest.yaml`
- `AGENTS.md`, anything in `.github/`
- `emissions_research/` (this is becoming production code; review it like service code)

For experiment-only changes, you may push directly to `main` if CI passes. For everything else, open a PR and wait for human review.

## Code quality

CI runs:
- `ruff format --check`
- `ruff check`
- `pytest` (only on `emissions_research/` and `tests/`; experiments are not test-gated)
- `mypy` (non-strict; reports issues but doesn't fail the build)

Coverage is not enforced in this repo.

## Promoting code from experiments to the service repo

When a piece of code in `emissions_research/` stabilizes (used in three experiments without API changes, has tests, has docstrings), it's a candidate to move to the service repo. The procedure:

1. Open an issue in `tijuana-dispersion-experiments` titled `promote: <module> to service repo`.
2. In the service repo, open a PR that imports the code, adds tests to bring it to 80% coverage, and updates `tijuana_dispersion/__init__.py` to expose it.
3. After the service-repo PR merges, open a follow-up PR in the experiments repo that removes the duplicated code and pins to the new service-repo dependency.

Do not duplicate. Code lives in one place at a time.

## NRP-specific conventions

When writing Dagster pipelines for NRP:

- Follow patterns from the `dagster-expert` skill — assets, partitions, sensors, and the implementation workflows it describes.
- Each pipeline run must have a unique `run_id`. Outputs land in object storage at `s3://<bucket>/dagster/runs/<run_id>/<asset_key>/`.
- **Use the `s3` and `slack` resources** (see `nrp/resources.py` and `nrp/dagster_pipeline.py`). Don't read S3 credentials or Slack webhook URLs directly from env vars in asset bodies — go through the resource. This is the integration point with the existing `tj_h2s_prediction` project; resources may be swapped for direct imports from that project later.
- **Use the `s3_io` IO manager for asset persistence.** Assets declared with `io_manager_key="s3_io"` automatically read/write through S3. Don't call `put_object` manually unless you specifically need to write a non-default format (e.g., parquet for big tabular outputs).
- **Slack notifications follow the policy in `nrp/README.md`.** Watch tier for run lifecycle (start, aggregator completion). Critical tier for failures and calibration regressions. Per-partition completions stay in the Dagster UI, never Slack.
- Resource limits go in Dagster job definitions (`op_tags`), not buried in K8s YAML.
- Heavy compute (HYSPLIT, STILT) runs in K8s pods invoked from Dagster, not in the Dagster process itself.
- Every pipeline is locally testable via `dagster dev` against a small mock dataset (in `tests/`).

## Calibration status log discipline

`docs/calibration_status.md` is the single source of truth for where the calibration is. Update it after every meaningful experiment. Format:

```
## YYYY-MM-DD — <experiment short name>

**Question**: ...
**Result**: ...
**State change**: <what we now believe vs before>
**Next**: <what experiment this points toward>
```

Don't delete old entries. The log is the history.

## When in doubt

- Open an issue describing the question.
- For experiments specifically, it is often better to *do* the experiment and write up "this didn't work because X" than to debate the design at length. Cheap to run; cheap to discard.
