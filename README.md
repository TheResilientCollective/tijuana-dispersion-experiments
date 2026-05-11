# tijuana-dispersion-experiments

Calibration runs, sensitivity analyses, emissions-model research, and NRP batch jobs for the Tijuana River Valley H₂S monitoring project.

The companion repo to [`tijuana-dispersion`](https://github.com/theresilientcollective/tijuana-dispersion). The service repo is small and stable; this repo is where research happens.

## Quick start

```
uv sync
python scripts/fetch_data.py    # populates data/raw/ from the manifest
ls experiments/
```

Each experiment is a self-contained folder under `experiments/<YYYY-MM-DD>_<short_name>/` with a `README.md` (hypothesis), `run.py` (the analysis), and `RESULTS.md` (what was learned).

To start a new experiment, copy `experiments/_template/` and fill in the README.

## Where things are

- `experiments/` — dated experiment folders, immutable once committed
- `notebooks/` — exploratory Jupyter; promoted to `experiments/` when stable
- `nrp/` — Dagster pipelines and K8s manifests for batch jobs on the National Research Platform
- `emissions_research/` — the river/estuary emissions model (pre-stable, will graduate to the service repo)
- `data/manifest.yaml` — declared data sources; fetch with `scripts/fetch_data.py`
- `docs/calibration_status.md` — the running log of calibration state. Read this first.

## Running on NRP

The Dagster pipeline in `nrp/dagster_pipeline.py` orchestrates batch dispersion runs that submit K8s jobs to NRP. See `nrp/README.md` and `docs/nrp_dagster.md`.

Local development:

```
cd nrp
dagster dev
```

Open http://localhost:3000 to see the asset graph.

## For AI coding agents

Read `AGENTS.md` at the start of every session. Skills installed: `dignified-python@dagster-skills` (always), `dagster-expert@dagster-skills` (when in `nrp/`).

Hard rule: no synthetic data fallbacks. If real data is missing, raise. This rule keeps calibration results trustworthy.

## License

MIT. See `LICENSE`.
