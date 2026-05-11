# Data

This directory holds the project's data dependencies. Only `manifest.yaml` and `README.md` are committed to git; everything else is fetched at runtime.

## Why fetch instead of commit

1. **Size.** The H₂S dataset is ~10+ MB and grows daily; complaint records and forecast data add more.
2. **Freshness.** Several files are refreshed daily or hourly upstream. Committed snapshots go stale fast.
3. **Reproducibility-by-pinning.** Experiments needing an exact snapshot pin the file (and ideally a sha256) in their `config.yaml`. The manifest is the *current* state; experiment configs are the *historical record* of what was used.

This is deliberately simpler than DVC. If we ever need full lineage, DVC slots in cleanly because the URL-and-checksum convention already exists.

## Fetching

```bash
uv run python scripts/fetch_data.py             # fetch all
uv run python scripts/fetch_data.py --status    # show what's already on disk
uv run python scripts/fetch_data.py --refresh modeldata_h2s_nofill   # re-fetch one
```

Checksums are verified for entries with `strict: true`.

## Adding a new dataset

1. Add an entry to `manifest.yaml` with a stable URL and a target path.
2. If the file is static, set `strict: true` and pin the sha256 (`scripts/fetch_data.py --update-checksums`).
3. If refreshed regularly, leave `strict: false` and `sha256: pending`.
4. Document the dataset's structure briefly here.

## Format preference

**Parquet over CSV.** Both versions are usually published; the manifest lists parquet as primary and CSV as fallback. Parquet preserves schema, types, and timezone-aware timestamps; CSV requires manual handling for the H₂S dataset's `America/Los_Angeles` index.

## Pinning data versions in experiments

In an experiment's `config.yaml`:

```yaml
data:
  modeldata_h2s_nofill:
    sha256: a3f5b2...               # pin to a specific snapshot
    fetched_on: 2026-05-05T00:00Z   # for human reference
```

The experiment's `run.py` should verify the checksum before running. A helper for this lives at `scripts/verify_data_pin.py`.
