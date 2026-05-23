"""Submit the Sobol workload to NRP via the Dagster GraphQL API.

Two modes:

1. **Single window** (the default) — submits one ``sobol_chunk_results``
   backfill at the configured fit window. After the chunks complete,
   the operator runs the printed follow-up ``dg launch`` to
   materialise ``sobol_aggregate`` + ``sobol_post_analysis``.

2. **Bulk windows** (``--windows-file path/to/windows.yaml``) — for
   each window in the YAML in order:
     a. submit the chunks backfill
     b. poll until the backfill terminates (every ``--poll-interval``)
     c. launch ``sobol_aggregate_job`` (aggregate + post-analysis)
        with matching config so the archive tag stays consistent
     d. poll until that run terminates
     e. print the archive tag, move on
   Sequential by design: the IO manager keys chunks by asset only, so
   parallel windows would race-overwrite each other. The durable
   per-run archive at ``s3://<bucket>/runs/<tag>/`` (written by
   ``sobol_post_analysis``) preserves each window permanently.

Examples
--------
    # Single window, full scale (default):
    uv run python nrp/scripts/submit_sobol.py

    # Single window, override:
    uv run python nrp/scripts/submit_sobol.py --n-base-samples 256
    uv run python nrp/scripts/submit_sobol.py \\
        --window-start 2026-05-10 --window-end 2026-05-12

    # Bulk multi-window from YAML:
    uv run python nrp/scripts/submit_sobol.py --windows-file windows.yaml
    uv run python nrp/scripts/submit_sobol.py --windows-file windows.yaml \\
        --start-from 2  # resume past previously-completed windows

    # Dry-run (single OR bulk):
    uv run python nrp/scripts/submit_sobol.py --dry-run
    uv run python nrp/scripts/submit_sobol.py --dry-run \\
        --windows-file windows.yaml

Requires a port-forward to the Dagster webserver:
    kubectl port-forward svc/dagster-webserver 3000:80 -n <ns>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

# Ensure the repo root is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from nrp.dagster_pipeline import N_SOBOL_CHUNKS
from nrp.sobol import DEFAULT_WINDOW, PARAM_RANGES, Window, load_windows, run_tag

URL = "http://localhost:3000/graphql"

# Below this base sample count, Sobol indices are not converged
# (see experiments/2026-05-15_sobol_full/RESULTS.md). A submission
# accidentally at N=16 is what the 2026-05-21 NRP run was — the
# pipeline ran perfectly but produced unusable indices. This warning
# is the postmortem: a smoke-sized N must be deliberate, not silent.
SMOKE_THRESHOLD = 1024

# Terminal statuses for Dagster backfills and runs (anything else = poll again).
_BACKFILL_TERMINAL = {"COMPLETED", "COMPLETED_SUCCESS", "FAILED", "CANCELED"}
_RUN_TERMINAL = {"SUCCESS", "FAILURE", "CANCELED"}


# ---------- GraphQL primitives ---------- #


def _gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """One-shot GraphQL POST against the port-forwarded webserver."""
    resp = requests.post(
        URL,
        json={"query": query, "variables": variables or {}},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def _submit_chunks_backfill(
    n_base_samples: int,
    seed: int,
    window_start: str,
    window_end: str,
) -> str | None:
    """Launch the 100-partition chunks backfill. Returns backfillId."""
    partitions = [f"chunk_{i:03d}" for i in range(N_SOBOL_CHUNKS)]
    run_config = json.dumps(
        {
            "ops": {
                "sobol_chunk_results": {
                    "config": {
                        "n_base_samples": n_base_samples,
                        "seed": seed,
                        "window_start": window_start,
                        "window_end": window_end,
                    },
                },
            },
        },
    )
    mutation = """
    mutation($partitions: [String!]!, $runConfigData: RunConfigData) {
      launchPartitionBackfill(backfillParams: {
        partitionNames: $partitions,
        assetSelection: [{ path: ["sobol_chunk_results"] }],
        runConfigData: $runConfigData,
      }) {
        ... on LaunchBackfillSuccess { backfillId }
        ... on PythonError { message }
      }
    }
    """
    result = _gql(mutation, {"partitions": partitions, "runConfigData": run_config})
    data = (result.get("data") or {}).get("launchPartitionBackfill", {})
    if "backfillId" in data:
        return data["backfillId"]
    print(f"Backfill submission failed: {data.get('message', result)}", file=sys.stderr)
    return None


def _poll_backfill(backfill_id: str, poll_interval_s: int, timeout_s: int) -> str:
    """Block until the backfill reaches a terminal status. Returns the status."""
    query = """
    query($id: String!) {
      partitionBackfillOrError(backfillId: $id) {
        ... on PartitionBackfill { status }
        ... on BackfillNotFoundError { message }
        ... on PythonError { message }
      }
    }
    """
    deadline = time.time() + timeout_s
    last_status = ""
    while time.time() < deadline:
        result = _gql(query, {"id": backfill_id})
        node = (result.get("data") or {}).get("partitionBackfillOrError", {})
        status = node.get("status", "UNKNOWN")
        if status != last_status:
            print(f"    backfill {backfill_id}: {status}")
            last_status = status
        if status in _BACKFILL_TERMINAL:
            return status
        if "message" in node and status == "UNKNOWN":
            return f"ERROR: {node['message']}"
        time.sleep(poll_interval_s)
    return "TIMEOUT"


def _launch_aggregate_job(
    n_base_samples: int,
    seed: int,
    window_start: str,
    window_end: str,
    location: str,
    repository: str,
) -> str | None:
    """Launch sobol_aggregate_job (aggregate + post-analysis). Returns runId."""
    run_config = json.dumps(
        {
            "ops": {
                "sobol_post_analysis": {
                    "config": {
                        "n_base_samples": n_base_samples,
                        "seed": seed,
                        "window_start": window_start,
                        "window_end": window_end,
                    },
                },
            },
        },
    )
    mutation = """
    mutation($execParams: ExecutionParams!) {
      launchPipelineExecution(executionParams: $execParams) {
        ... on LaunchRunSuccess { run { runId } }
        ... on RunConfigValidationInvalid { errors { message } }
        ... on PipelineNotFoundError { message }
        ... on PythonError { message }
      }
    }
    """
    exec_params = {
        "selector": {
            "repositoryLocationName": location,
            "repositoryName": repository,
            "pipelineName": "sobol_aggregate_job",
        },
        "runConfigData": run_config,
    }
    result = _gql(mutation, {"execParams": exec_params})
    node = (result.get("data") or {}).get("launchPipelineExecution", {})
    run = node.get("run")
    if run and "runId" in run:
        return run["runId"]
    print(
        f"Aggregate-job submission failed: {node.get('message') or node.get('errors') or result}",
        file=sys.stderr,
    )
    return None


def _poll_run(run_id: str, poll_interval_s: int, timeout_s: int) -> str:
    """Block until the run reaches a terminal status. Returns the status."""
    query = """
    query($id: ID!) {
      runOrError(runId: $id) {
        ... on Run { status }
        ... on RunNotFoundError { message }
        ... on PythonError { message }
      }
    }
    """
    deadline = time.time() + timeout_s
    last_status = ""
    while time.time() < deadline:
        result = _gql(query, {"id": run_id})
        node = (result.get("data") or {}).get("runOrError", {})
        status = node.get("status", "UNKNOWN")
        if status != last_status:
            print(f"    run {run_id[:8]}: {status}")
            last_status = status
        if status in _RUN_TERMINAL:
            return status
        if "message" in node and status == "UNKNOWN":
            return f"ERROR: {node['message']}"
        time.sleep(poll_interval_s)
    return "TIMEOUT"


# ---------- windows loader ---------- #


# ---------- single-window planning (shared by both modes) ---------- #


def _print_plan_header(
    n_base_samples: int,
    seed: int,
    window_start: str,
    window_end: str,
    note: str = "",
) -> None:
    d = len(PARAM_RANGES)
    total = n_base_samples * (d + 2)
    rows = -(-total // N_SOBOL_CHUNKS)
    scale = "FULL-SCALE" if n_base_samples >= SMOKE_THRESHOLD else "SMOKE — NOT FOR SCIENCE"
    print(f"  scale          : {scale}")
    print(f"  N (base)       : {n_base_samples}")
    print(f"  total samples  : {total:,}")
    print(f"  ~rows / chunk  : {rows:,}")
    print(f"  window         : {window_start} → {window_end}" + (f"  ({note})" if note else ""))
    print(f"  seed           : {seed}")


def _smoke_warning_if_needed(n_base_samples: int) -> None:
    if n_base_samples < SMOKE_THRESHOLD:
        print(
            f"!! WARNING: N={n_base_samples} is below {SMOKE_THRESHOLD} — Sobol indices will\n"
            "   not be converged at this scale (the May 2026 first run hit this exactly).\n"
            "   Pass --n-base-samples 8192 for a publishable result.\n",
            file=sys.stderr,
        )


# ---------- run one window (chunks → aggregate-job) ---------- #


def run_one_window(
    window: Window,
    n_base_samples: int,
    seed: int,
    poll_interval_s: int,
    backfill_timeout_s: int,
    aggregate_timeout_s: int,
    location: str,
    repository: str,
    skip_aggregate: bool,
) -> tuple[str, str]:
    """Run one window's full chain. Returns (status, archive_tag).

    status ∈ {"OK", "BACKFILL_FAILED", "AGGREGATE_FAILED", "TIMEOUT", "SUBMIT_FAILED"}
    """
    tag = run_tag(window.start, window.end, n_base_samples, seed)
    print(
        f"\n=== window {window.start} → {window.end} "
        f"{('(' + window.note + ')') if window.note else ''}"
    )
    print(f"  archive tag    : runs/{tag}")

    backfill_id = _submit_chunks_backfill(n_base_samples, seed, window.start, window.end)
    if not backfill_id:
        return "SUBMIT_FAILED", tag
    print(f"  backfill       : {backfill_id}")

    status = _poll_backfill(backfill_id, poll_interval_s, backfill_timeout_s)
    if status not in {"COMPLETED", "COMPLETED_SUCCESS"}:
        return ("TIMEOUT" if status == "TIMEOUT" else "BACKFILL_FAILED"), tag

    if skip_aggregate:
        print("  (--skip-aggregate set; not launching sobol_aggregate_job)")
        return "OK", tag

    run_id = _launch_aggregate_job(
        n_base_samples,
        seed,
        window.start,
        window.end,
        location,
        repository,
    )
    if not run_id:
        return "AGGREGATE_FAILED", tag
    print(f"  aggregate run  : {run_id[:8]}")

    rstatus = _poll_run(run_id, poll_interval_s, aggregate_timeout_s)
    if rstatus != "SUCCESS":
        return ("TIMEOUT" if rstatus == "TIMEOUT" else "AGGREGATE_FAILED"), tag

    print(f"  ✓ done; archive at s3://$DAGSTER_S3_BUCKET/runs/{tag}/")
    return "OK", tag


# ---------- main ---------- #


def main() -> int:
    ap = argparse.ArgumentParser(description="Submit Sobol workload(s) via Dagster GraphQL.")
    ap.add_argument(
        "--n-base-samples",
        type=int,
        default=8192,
        help="SALib base N (total = N*(D+2)). Default 8192 (publishable).",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--window-start", default=DEFAULT_WINDOW[0])
    ap.add_argument("--window-end", default=DEFAULT_WINDOW[1])
    ap.add_argument(
        "--windows-file",
        type=Path,
        help="YAML file with a 'windows' list — bulk-mode: each window runs sequentially.",
    )
    ap.add_argument(
        "--start-from",
        type=int,
        default=1,
        help="Bulk mode: skip the first N-1 windows (1-indexed). Resume after a failure.",
    )
    ap.add_argument("--dry-run", action="store_true", help="Print the plan, don't submit.")
    ap.add_argument(
        "--skip-aggregate",
        action="store_true",
        help="Submit chunks only; skip the aggregate+post-analysis follow-up.",
    )
    ap.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Bulk mode: keep going after a window fails (default: fail-fast).",
    )
    ap.add_argument("--poll-interval", type=int, default=30, help="Seconds between status polls.")
    ap.add_argument(
        "--backfill-timeout-mins",
        type=int,
        default=90,
        help="Per-window backfill timeout. Typical NRP run completes in ~30 min.",
    )
    ap.add_argument(
        "--aggregate-timeout-mins",
        type=int,
        default=15,
        help="Per-window aggregate+post-analysis timeout (typically < 1 min).",
    )
    ap.add_argument(
        "--code-location",
        default="nrp",
        help="Dagster code location name (Helm dagster-user-deployments name).",
    )
    ap.add_argument(
        "--repository",
        default="__repository__",
        help="Dagster repository within the code location.",
    )
    args = ap.parse_args()

    # ---- Single-window mode (backward compatible) ----
    if not args.windows_file:
        windows = [Window(args.window_start, args.window_end, note="(single-window mode)")]
    else:
        try:
            windows = load_windows(args.windows_file)
        except (yaml.YAMLError, ValueError, FileNotFoundError) as e:
            print(f"error loading {args.windows_file}: {e}", file=sys.stderr)
            return 2

    if args.start_from > 1:
        windows = windows[args.start_from - 1 :]
        if not windows:
            print(
                f"--start-from {args.start_from} skips all windows; nothing to do.", file=sys.stderr
            )
            return 1

    _smoke_warning_if_needed(args.n_base_samples)

    print("=== Sobol submission plan ===")
    print(
        f"  windows         : {len(windows)}"
        + (f"  (loaded from {args.windows_file})" if args.windows_file else "")
    )
    for i, w in enumerate(windows, start=1):
        print(f"\n  [{i}/{len(windows)}]")
        _print_plan_header(args.n_base_samples, args.seed, w.start, w.end, w.note)
        print(f"  archive tag    : runs/{run_tag(w.start, w.end, args.n_base_samples, args.seed)}")

    if args.dry_run:
        print("\n[dry-run] NOT submitted.")
        return 0

    backfill_timeout_s = args.backfill_timeout_mins * 60
    aggregate_timeout_s = args.aggregate_timeout_mins * 60

    results: list[tuple[Window, str, str]] = []
    for i, w in enumerate(windows, start=1):
        print(f"\n──── window {i}/{len(windows)} ────")
        status, tag = run_one_window(
            w,
            args.n_base_samples,
            args.seed,
            args.poll_interval,
            backfill_timeout_s,
            aggregate_timeout_s,
            args.code_location,
            args.repository,
            args.skip_aggregate,
        )
        results.append((w, status, tag))
        if status != "OK" and not args.continue_on_error:
            print(
                f"\n!! window {i} failed with status={status}; stopping (use "
                f"--continue-on-error to keep going, --start-from {i + 1} to resume past it).",
                file=sys.stderr,
            )
            break

    # Summary
    print("\n=== Summary ===")
    for i, (w, status, tag) in enumerate(results, start=1):
        marker = "✓" if status == "OK" else "✗"
        print(f"  {marker} [{i}] {w.start} → {w.end}  status={status}  tag=runs/{tag}")

    return 0 if all(r[1] == "OK" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
