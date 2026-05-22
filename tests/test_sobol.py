"""Unit tests for the Sobol workload science (nrp/sobol.py, issue #2).

These cover the framework-agnostic core: deterministic sampling, chunk
coverage, the reassembly guard, and the SALib analysis shape. The
Dagster asset wiring (per-partition K8s fan-out, AllPartitionMapping
load) is exercised on NRP / via the Dagster daemon, not here — these
tests pin the science so a bad refactor is caught fast.

The one data-dependent test is skipped when the H2S parquet is absent
(e.g. CI without a data fetch); it is a real integration check, not a
synthetic stand-in (AGENTS.md: no fabricated observations).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nrp import sobol


def test_build_samples_is_deterministic() -> None:
    a = sobol.build_samples(8, seed=42)
    b = sobol.build_samples(8, seed=42)
    assert a.shape == (8 * (11 + 2), 11)  # SALib: N*(D+2), calc_second_order=False
    np.testing.assert_array_equal(a, b)


def test_build_samples_seed_changes_matrix() -> None:
    assert not np.array_equal(sobol.build_samples(8, seed=1), sobol.build_samples(8, seed=2))


def test_build_samples_within_bounds() -> None:
    X = sobol.build_samples(16, seed=42)
    for j, name in enumerate(sobol.build_problem()["names"]):
        lo, hi = sobol.PARAM_RANGES[name]
        assert X[:, j].min() >= lo - 1e-9
        assert X[:, j].max() <= hi + 1e-9


def test_chunk_bounds_partition_exactly_once() -> None:
    n_rows = 8 * 13  # 104
    bounds = sobol.chunk_bounds(n_rows, 100)
    assert len(bounds) == 100
    # contiguous, non-overlapping, covers [0, n_rows)
    covered: list[int] = []
    prev_end = 0
    for start, end in bounds:
        assert start == prev_end
        assert end >= start
        covered.extend(range(start, end))
        prev_end = end
    assert covered == list(range(n_rows))


def test_chunk_bounds_more_chunks_than_rows() -> None:
    bounds = sobol.chunk_bounds(5, 100)
    # first 5 chunks get one row, rest empty; union still covers [0,5)
    nonempty = [(s, e) for s, e in bounds if e > s]
    assert sum(e - s for s, e in nonempty) == 5


def test_output_columns_are_3x3() -> None:
    assert len(sobol.OUTPUT_COLUMNS) == 9
    assert set(sobol.METRIC_KINDS) == {"rms", "corr", "peak_ratio"}


def test_reassemble_rejects_incomplete_matrix() -> None:
    # Two chunks declaring a 4-row matrix but only 3 rows present.
    chunks = {
        "chunk_000": {
            "start": 0,
            "end": 2,
            "param_names": ["a"],
            "metric_columns": ["m"],
            "rows": [{"_row": 0, "m": 1.0}, {"_row": 1, "m": 2.0}],
        },
        "chunk_001": {
            "start": 2,
            "end": 4,
            "param_names": ["a"],
            "metric_columns": ["m"],
            "rows": [{"_row": 2, "m": 3.0}],  # row 3 missing
        },
    }
    with pytest.raises(ValueError, match="incomplete"):
        sobol.reassemble(chunks)


def test_reassemble_orders_rows_globally() -> None:
    chunks = {
        # Deliberately out of key order to prove global-index placement.
        "chunk_001": {
            "start": 2,
            "end": 4,
            "param_names": ["a"],
            "metric_columns": ["m"],
            "rows": [{"_row": 3, "m": 30.0}, {"_row": 2, "m": 20.0}],
        },
        "chunk_000": {
            "start": 0,
            "end": 2,
            "param_names": ["a"],
            "metric_columns": ["m"],
            "rows": [{"_row": 1, "m": 10.0}, {"_row": 0, "m": 0.0}],
        },
    }
    asm = sobol.reassemble(chunks)
    np.testing.assert_array_equal(asm["y_by_metric"]["m"], np.array([0.0, 10.0, 20.0, 30.0]))
    assert asm["n_samples"] == 4


def test_reassemble_empty_raises() -> None:
    with pytest.raises(ValueError, match="nothing to analyse"):
        sobol.reassemble({"chunk_000": {"start": 0, "end": 0, "rows": []}})


def test_analyze_returns_indices_per_parameter() -> None:
    problem = sobol.build_problem()
    X = sobol.build_samples(16, seed=42)
    # Monotone-in-one-param response → that param dominates S1/ST.
    y = 5.0 * X[:, 0] + 0.01 * X[:, 1]
    df = sobol.analyze(problem, y)
    assert list(df["parameter"]) == problem["names"]
    assert {"S1", "S1_conf", "ST", "ST_conf"} <= set(df.columns)
    top = df.sort_values("ST", ascending=False).iloc[0]
    assert top["parameter"] == "baseline_scale"  # column 0


# ---------- post-analysis helpers (added in the postmortem PR) ---------- #


def _synthetic_indices(
    params: list[str],
    metrics: list[str],
    st_map: dict[tuple[str, str], float] | None = None,
) -> pd.DataFrame:
    """Build a deterministic indices frame for the post-analysis tests.

    ``st_map[(metric, param)] = ST``; defaults to a small constant.
    S1 = 0.4 × ST (so interaction = 0.6 × ST). Conf is held tiny
    (0.01 × ST) so the converged-case test sees ratio ≈ 0.01.
    """
    rows = []
    for m in metrics:
        for p in params:
            st = (st_map or {}).get((m, p), 0.05)
            conf = max(0.01 * abs(st), 1e-4)
            rows.append(
                {
                    "metric": m,
                    "parameter": p,
                    "S1": 0.4 * st,
                    "S1_conf": conf,
                    "ST": st,
                    "ST_conf": conf,
                },
            )
    return pd.DataFrame(rows)


def test_convergence_diagnostics_converged() -> None:
    df = _synthetic_indices(["a", "b", "c"], ["rms__r1", "corr__r1"])
    diag = sobol.convergence_diagnostics(df)
    assert diag["is_converged"] is True
    assert diag["rows_with_negative_s1"] == 0
    assert diag["st_conf_over_st_median"] < 0.20


def test_convergence_diagnostics_under_sampled_signature() -> None:
    # Mimic the smoke-run signature: S1 strongly negative, ST_conf large.
    rows = [
        {"metric": "rms__r1", "parameter": p, "S1": -0.3, "S1_conf": 0.5, "ST": 0.1, "ST_conf": 0.9}
        for p in ("a", "b", "c", "d")
    ]
    diag = sobol.convergence_diagnostics(pd.DataFrame(rows))
    assert diag["is_converged"] is False
    assert diag["rows_with_negative_s1"] == 4
    assert diag["st_conf_over_st_median"] > 1.0


def test_global_ranking_sorts_by_mean_st() -> None:
    df = _synthetic_indices(
        ["loud", "quiet"],
        ["rms__r1", "corr__r1"],
        st_map={
            ("rms__r1", "loud"): 0.5,
            ("corr__r1", "loud"): 0.4,
            ("rms__r1", "quiet"): 0.01,
            ("corr__r1", "quiet"): 0.01,
        },
    )
    g = sobol.global_ranking(df)
    assert list(g["parameter"]) == ["loud", "quiet"]
    assert g.iloc[0]["mean_ST"] > g.iloc[1]["mean_ST"]


def test_top_n_per_metric_shape_and_ordering() -> None:
    df = _synthetic_indices(
        ["a", "b", "c"],
        ["rms__r1"],
        st_map={("rms__r1", "a"): 0.1, ("rms__r1", "b"): 0.5, ("rms__r1", "c"): 0.3},
    )
    top = sobol.top_n_per_metric(df, n=2)
    assert list(top["parameter"]) == ["b", "c"]
    assert list(top["rank"]) == [1, 2]


def test_magnitude_vs_shape_split_partitions_metrics() -> None:
    df = _synthetic_indices(
        ["a"],
        ["rms__r1", "peak_ratio__r1", "corr__r1"],
        st_map={("rms__r1", "a"): 0.3, ("peak_ratio__r1", "a"): 0.4, ("corr__r1", "a"): 0.7},
    )
    split = sobol.magnitude_vs_shape_split(df)
    # magnitude side averages rms + peak_ratio = 0.35; shape is corr = 0.70
    assert split["magnitude"].iloc[0]["mean_ST"] == 0.35
    assert split["shape"].iloc[0]["mean_ST"] == 0.70


def test_interaction_table_filters_below_threshold() -> None:
    df = _synthetic_indices(
        ["a", "b"],
        ["rms__r1"],
        st_map={("rms__r1", "a"): 0.5, ("rms__r1", "b"): 0.05},
    )
    # ST-S1 = 0.6 × ST; threshold 0.10 excludes b (0.03), keeps a (0.30)
    it = sobol.interaction_table(df, min_interaction=0.10)
    assert list(it["parameter"]) == ["a"]


def test_dropout_candidates_flags_max_st_below_threshold() -> None:
    df = _synthetic_indices(
        ["dead", "alive"],
        ["rms__r1", "corr__r1"],
        st_map={
            ("rms__r1", "dead"): 0.001,
            ("corr__r1", "dead"): 0.001,
            ("rms__r1", "alive"): 0.3,
            ("corr__r1", "alive"): 0.4,
        },
    )
    assert sobol.dropout_candidates(df, max_st_threshold=0.02) == ["dead"]


def test_run_tag_is_deterministic() -> None:
    t = sobol.run_tag("2026-03-13", "2026-03-16", 8192, 42, run_date="2026-05-22")
    assert t == "2026-03-13_2026-03-16_N8192_seed42_2026-05-22"


# ---------- bulk-windows YAML loader (submit_sobol.py --windows-file) ---------- #


def test_load_windows_happy_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "windows.yaml"
    p.write_text(
        "windows:\n"
        "  - {start: '2026-03-13', end: '2026-03-16', note: 'advective'}\n"
        "  - {start: '2026-05-10', end: '2026-05-12'}\n",
    )
    ws = sobol.load_windows(p)
    assert len(ws) == 2
    assert ws[0].start == "2026-03-13"
    assert ws[0].note == "advective"
    assert ws[1].note == ""  # optional


def test_load_windows_rejects_missing_keys(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "bad.yaml"
    p.write_text("windows:\n  - {start: '2026-03-13'}\n")  # missing 'end'
    with pytest.raises(ValueError, match="missing 'start' and/or 'end'"):
        sobol.load_windows(p)


def test_load_windows_rejects_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "empty.yaml"
    p.write_text("windows: []\n")
    with pytest.raises(ValueError, match="non-empty list"):
        sobol.load_windows(p)


def test_load_windows_rejects_no_top_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "shape.yaml"
    p.write_text("- start: '2026-03-13'\n  end: '2026-03-16'\n")  # list at top, not a mapping
    with pytest.raises(ValueError, match="must be a mapping with a 'windows' list"):
        sobol.load_windows(p)


def test_load_windows_rejects_non_dict_item(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "weird.yaml"
    p.write_text("windows:\n  - 'just-a-string'\n")
    with pytest.raises(ValueError, match=r"windows\[0\] must be a mapping"):
        sobol.load_windows(p)


# ---------- data-dependent integration check ---------- #


@pytest.mark.skipif(
    not sobol.DEFAULT_PARQUET.exists(),
    reason="H2S parquet not fetched; skipping the data-dependent integration check",
)
def test_evaluate_sample_real_data_shapes() -> None:
    # Needs the deferred `service` extra (forward model). Absent in this
    # repo's CI (`uv sync --extra dev`) → skip cleanly; this is the one
    # real integration check, run locally / on the NRP worker image.
    pytest.importorskip("tijuana_dispersion")
    df = sobol.load_window(sobol.DEFAULT_PARQUET, sobol.DEFAULT_WINDOW)
    drivers, met, hours = sobol.make_drivers_and_met(df)
    obs = sobol.build_obs(df, hours, sobol.RECEPTOR_NAMES)
    assert len(drivers) == len(met) > 5
    X = sobol.build_samples(4, seed=42)
    out = sobol.evaluate_sample(X[0], sobol.build_problem()["names"], drivers, met, obs)
    assert set(out) == set(sobol.OUTPUT_COLUMNS)
    # At least one receptor with obs should yield a finite RMS.
    assert any(np.isfinite(v) for k, v in out.items() if k.startswith("rms__"))
