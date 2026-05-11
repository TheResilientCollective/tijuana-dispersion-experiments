# <experiment slug here>

**Date:** <YYYY-MM-DD>
**Status:** <planning | running | done | abandoned>
**Author:** <name or @handle>

## Question

What scientific or engineering question does this experiment answer? One paragraph.

## Approach

What we're doing to answer it. Methodology, data, comparison cases. One to three paragraphs.

## How to reproduce

```bash
cd experiments/<this-folder>
uv run python run.py
```

Inputs are in `config.yaml`. Outputs land in `outputs/` (git-ignored). Results are summarized in `RESULTS.md`.

## Dependencies

- `tijuana-dispersion` at commit `<sha or main>`
- Data: see `data:` section in `config.yaml` for pinned files

## Notes

Anything else relevant. Often left empty until results come in.
