# Results — <experiment slug>

**Run on:** <YYYY-MM-DD>
**Runtime:** <e.g., 9 seconds, 4 minutes, 2 NRP CPU-hours>
**Outputs:** in `outputs/` (not committed)

## Question

(Restate from `README.md` for at-a-glance reading.)

## What we did

A few sentences describing the actual run, including any deviations from `config.yaml`. If something changed mid-run, say so here.

## Key findings

The 1–3 most important things this experiment learned. Be specific:

- "NESTOR fit improved from r=0.27 to r=0.56 with bounded NNLS."
- "f_arch_estuary is the dominant sensitivity (Pearson r=-0.64 against NESTOR timing)."

Avoid vague summaries like "the model worked." If you find yourself writing that, the experiment didn't tell us anything.

## Numbers

Concrete metrics, ideally as a table:

| Metric | Value | Compared to baseline |
|---|---|---|
| ... | ... | ... |

## What this means

How does this finding affect what we do next? One paragraph.

## What should be done next

Specific follow-ups, ranked by value. Each should be small enough to be its own experiment.

1. ...
2. ...
3. ...

## Limitations / caveats

Honest accounting of what this experiment can't tell us, and why. Often more important than the findings themselves for avoiding overinterpretation.

## Files

- `outputs/<filename>.csv` — what's in it
- `outputs/<plot>.png` — what's in it
