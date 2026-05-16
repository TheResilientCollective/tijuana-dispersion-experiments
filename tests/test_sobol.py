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


@pytest.mark.skipif(
    not sobol.DEFAULT_PARQUET.exists(),
    reason="H2S parquet not fetched; skipping the data-dependent integration check",
)
def test_evaluate_sample_real_data_shapes() -> None:
    df = sobol.load_window(sobol.DEFAULT_PARQUET, sobol.DEFAULT_WINDOW)
    drivers, met, hours = sobol.make_drivers_and_met(df)
    obs = sobol.build_obs(df, hours, sobol.RECEPTOR_NAMES)
    assert len(drivers) == len(met) > 5
    X = sobol.build_samples(4, seed=42)
    out = sobol.evaluate_sample(X[0], sobol.build_problem()["names"], drivers, met, obs)
    assert set(out) == set(sobol.OUTPUT_COLUMNS)
    # At least one receptor with obs should yield a finite RMS.
    assert any(np.isfinite(v) for k, v in out.items() if k.startswith("rms__"))
