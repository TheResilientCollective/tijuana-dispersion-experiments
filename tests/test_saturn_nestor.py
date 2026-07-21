"""Unit tests for the Saturn→Nestor HYSPLIT science core (nrp/saturn_nestor.py
+ nrp/metfetch.py filename logic).

Same CI contract as test_sobol.py: no HYSPLIT binary, no network, no
``service`` extra. The synthetic cdump bytes are built by a test-local packer
that follows the HYSPLIT binary format (big-endian Fortran sequential
records) — mock data lives only in tests, per AGENTS.md.
"""

from __future__ import annotations

import struct

import numpy as np
import pandas as pd
import pytest

from nrp import metfetch, saturn_nestor

# ---------------------------------------------------------------------------
# CONTROL generation
# ---------------------------------------------------------------------------


def test_backward_control_lines() -> None:
    obs_hour = pd.Timestamp("2026-04-04 22:00")  # 15:00 PDT peak hour, naive UTC
    text = saturn_nestor.write_backward_control(
        obs_hour, 12, "/data/hysplit/meteo", ["gdas1.apr26.w1"]
    )
    lines = text.splitlines()
    assert lines[0] == "26 04 04 22"
    assert lines[1] == "1"
    assert lines[2] == "32.567097 -117.090656 10.0"  # NESTOR receptor, 10 m AGL
    assert lines[3] == "-12"  # negative = backward
    assert lines[4] == "0"
    assert lines[5] == "10000.0"
    assert lines[6] == "1"
    assert lines[7] == "/data/hysplit/meteo/"
    assert lines[8] == "gdas1.apr26.w1"
    assert lines[9] == "1"
    assert lines[10] == "H2S"
    assert lines[11] == "1.0"  # unit emission g/hr
    assert lines[12] == "1.0"  # 1-hour release = the obs averaging period
    assert lines[13] == "26 04 04 22 00"
    # Concentration grid: CENTER / SPACING / SPAN (not corner + cell counts).
    assert lines[14] == "1"
    assert lines[15] == "32.5632 -117.0918"
    assert lines[16] == "0.005 0.005"
    assert lines[17] == "0.20 0.20"
    assert lines[20] == "1"  # one level
    assert lines[21] == "10"
    assert lines[24] == "00 1 00"  # 1-hour averaging bins
    # Deposition block: gas, all zeros.
    assert lines[25] == "1"
    assert lines[-1] == "0.0"


def test_forward_control_prior_rate_is_g_per_hr() -> None:
    """5 g/s prior must land in CONTROL as 18000 g/hr (the field is per-hour)."""
    start = pd.Timestamp("2026-04-02 19:00")
    text = saturn_nestor.write_forward_control(
        start, 84, 5.0 * 3600.0, "/met", ["a", "b"], use_emitimes=False
    )
    lines = text.splitlines()
    assert lines[0] == "26 04 02 19"
    assert lines[2] == "32.559383 -117.092992 2.0"  # Saturn source, 2 m AGL
    assert lines[3] == "84"
    assert lines[6] == "2"  # two met files → dir/file pairs
    assert lines[7] == "/met/"
    assert lines[8] == "a"
    assert lines[9] == "/met/"
    assert lines[10] == "b"
    assert lines[13] == "18000.0000"
    assert lines[14] == "84.0"


def test_forward_control_emitimes_zeroes_rate() -> None:
    text = saturn_nestor.write_forward_control(
        pd.Timestamp("2026-04-02 19:00"), 84, 12345.0, "/met", ["a"], use_emitimes=True
    )
    lines = text.splitlines()
    assert lines[11] == "0.0000"
    assert lines[12] == "0.0"


def test_setup_cfg_efile_variant() -> None:
    base = saturn_nestor.setup_cfg(numpar=2500)
    assert "NUMPAR  = 2500," in base
    assert "EFILE" not in base
    with_e = saturn_nestor.setup_cfg(use_emitimes=True)
    assert "EFILE   = 'EMITIMES'," in with_e


def test_emitimes_records() -> None:
    idx = pd.date_range("2026-04-03 12:00", periods=3, freq="h")
    text = saturn_nestor.write_emitimes(pd.Series([3600.0, np.nan, 7200.0], index=idx))
    lines = text.splitlines()
    assert lines[2] == "2026 04 03 12 0003 3"  # cycle header: 3 h, 3 records
    assert lines[3] == "2026 04 03 12 00 0100 32.559383 -117.092992 2.0 3600.0000 0.0 0.0"
    assert lines[4].endswith(" 0.0000 0.0 0.0")  # NaN hour → 0-rate record
    assert lines[5] == "2026 04 03 14 00 0100 32.559383 -117.092992 2.0 7200.0000 0.0 0.0"


# ---------------------------------------------------------------------------
# Met filenames
# ---------------------------------------------------------------------------


def test_gdas1_single_week() -> None:
    files = metfetch.met_files_for("gdas1", pd.Timestamp("2026-04-03"), pd.Timestamp("2026-04-06"))
    assert [f.name for f in files] == ["gdas1.apr26.w1"]
    assert files[0].key == "gdas1/2026/gdas1.apr26.w1"


def test_gdas1_backward_reach_crosses_month() -> None:
    """Apr 1 02:00 UTC − 12 h reaches Mar 31 (week 5)."""
    start = pd.Timestamp("2026-04-01 02:00") - pd.Timedelta(hours=12)
    files = metfetch.met_files_for("gdas1", start, pd.Timestamp("2026-04-01 02:00"))
    assert [f.name for f in files] == ["gdas1.mar26.w5", "gdas1.apr26.w1"]


def test_hrrr_blocks_cover_interval() -> None:
    files = metfetch.met_files_for(
        "hrrr", pd.Timestamp("2026-04-03 21:00"), pd.Timestamp("2026-04-04 03:00")
    )
    assert [f.name for f in files] == ["20260403_18-23_hrrr", "20260404_00-05_hrrr"]
    assert files[0].key == "hrrr/2026/04/20260403_18-23_hrrr"
    # HRRR sanity floor is the larger one (3.4 GB chunks vs 600 MB weeks).
    assert files[0].min_bytes > metfetch._MIN_BYTES["gdas1"]


def test_met_files_default_window_hrrr_count() -> None:
    """3-day window + 12 h reach ≈ 15 six-hour HRRR chunks (~51 GB)."""
    start = pd.Timestamp("2026-04-03 07:00") - pd.Timedelta(hours=12)
    files = metfetch.met_files_for("hrrr", start, pd.Timestamp("2026-04-06 06:00"))
    assert len(files) == 15


def test_unknown_met_source_raises() -> None:
    with pytest.raises(ValueError, match="met_source"):
        metfetch.met_files_for("wrf", pd.Timestamp("2026-04-03"), pd.Timestamp("2026-04-04"))


# ---------------------------------------------------------------------------
# cdump parsing (synthetic byte round-trip)
# ---------------------------------------------------------------------------

_NLAT, _NLON = 5, 4
_CLAT, _CLON = 32.55, -117.10
_DLAT = _DLON = 0.005


def _rec(payload: bytes) -> bytes:
    return struct.pack(">i", len(payload)) + payload + struct.pack(">i", len(payload))


def _pack_cdump(grids: list[np.ndarray], packing: int) -> bytes:
    """Synthetic HYSPLIT cdump: header, 1 release loc, grid def, 1 level,
    1 pollutant, then one (start, stop, conc) record set per grid."""
    out = _rec(struct.pack(">4siiiiiii", b"TEST", 26, 4, 4, 10, 0, 1, packing))
    out += _rec(struct.pack(">iiiiffff", 26, 4, 4, 10, 32.567, -117.09, 10.0, 0.0))
    out += _rec(struct.pack(">iiffff", _NLAT, _NLON, _DLAT, _DLON, _CLAT, _CLON))
    out += _rec(struct.pack(">ii", 1, 10))
    out += _rec(struct.pack(">i4s", 1, b"H2S "))
    for t_idx, grid in enumerate(grids):
        hour = 10 + t_idx
        out += _rec(struct.pack(">iiiiii", 26, 4, 4, hour, 0, 0))
        out += _rec(struct.pack(">iiiiii", 26, 4, 4, hour + 1, 0, 0))
        header = struct.pack(">4si", b"H2S ", 10)
        if packing == 0:
            body = struct.pack(f">{grid.size}f", *grid.ravel().tolist())
        else:
            nz = [
                (j + 1, i + 1, float(grid[i, j]))
                for i in range(_NLAT)
                for j in range(_NLON)
                if grid[i, j] != 0
            ]
            body = struct.pack(">i", len(nz))
            for lon_i, lat_i, val in nz:
                body += struct.pack(">hh", lon_i, lat_i) + struct.pack(">f", val)
        out += _rec(header + body)
    return out


@pytest.mark.parametrize("packing", [0, 1])
def test_parse_cdump_round_trip(tmp_path, packing: int) -> None:
    g0 = np.zeros((_NLAT, _NLON), dtype=np.float32)
    g0[2, 1] = 3.5e-9
    g1 = np.zeros((_NLAT, _NLON), dtype=np.float32)
    g1[4, 3] = 1.0e-10
    path = tmp_path / "cdump"
    path.write_bytes(_pack_cdump([g0, g1], packing))

    grid = saturn_nestor.parse_cdump(path)
    assert grid.conc.shape == (2, _NLAT, _NLON)
    np.testing.assert_allclose(grid.conc[0], g0, rtol=1e-6)
    np.testing.assert_allclose(grid.conc[1], g1, rtol=1e-6)
    np.testing.assert_allclose(grid.lats, _CLAT + np.arange(_NLAT) * _DLAT, rtol=1e-5)
    np.testing.assert_allclose(grid.lons, _CLON + np.arange(_NLON) * _DLON, rtol=1e-5)
    assert grid.times[0] == pd.Timestamp("2026-04-04 11:00")  # bin STOP time
    assert grid.times[1] == pd.Timestamp("2026-04-04 12:00")


def test_parse_cdump_truncated_raises(tmp_path) -> None:
    blob = _pack_cdump([np.ones((_NLAT, _NLON), dtype=np.float32)], 0)
    path = tmp_path / "cdump"
    path.write_bytes(blob[: len(blob) // 2])
    with pytest.raises(ValueError):
        saturn_nestor.parse_cdump(path)


def test_parse_cdump_empty_raises(tmp_path) -> None:
    path = tmp_path / "cdump"
    path.write_bytes(b"")
    with pytest.raises(ValueError, match="Empty"):
        saturn_nestor.parse_cdump(path)


# ---------------------------------------------------------------------------
# Cell sampling + sensitivity
# ---------------------------------------------------------------------------


def _grid_covering_sources(conc: np.ndarray) -> saturn_nestor.CdumpGrid:
    """41×41 grid matching the production GRID config (center/span/spacing)."""
    g = saturn_nestor.GRID
    n = int(g["span_deg"] / g["spacing_deg"]) + 1
    lat0 = g["center_lat"] - g["span_deg"] / 2
    lon0 = g["center_lon"] - g["span_deg"] / 2
    return saturn_nestor.CdumpGrid(
        times=[
            pd.Timestamp("2026-04-04 11:00") + pd.Timedelta(hours=k) for k in range(conc.shape[0])
        ],
        lats=lat0 + np.arange(n) * g["spacing_deg"],
        lons=lon0 + np.arange(n) * g["spacing_deg"],
        conc=conc,
    )


def test_saturn_and_nestor_land_in_distinct_cells() -> None:
    grid = _grid_covering_sources(np.zeros((1, 41, 41)))
    _, slat, slon, _ = saturn_nestor.SOURCE
    _, rlat, rlon, _ = saturn_nestor.RECEPTOR
    assert saturn_nestor.cell_index(grid, slat, slon) != saturn_nestor.cell_index(grid, rlat, rlon)


def test_cell_index_outside_grid_raises() -> None:
    grid = _grid_covering_sources(np.zeros((1, 41, 41)))
    with pytest.raises(ValueError, match="outside"):
        saturn_nestor.cell_index(grid, 33.5, -118.5)


def test_sensitivity_sums_bins_at_saturn_cell() -> None:
    conc = np.zeros((3, 41, 41))
    _, slat, slon, _ = saturn_nestor.SOURCE
    grid = _grid_covering_sources(conc)
    i, j = saturn_nestor.cell_index(grid, slat, slon)
    conc[0, i, j] = 2.0e-9
    conc[2, i, j] = 1.0e-9
    sens, n_nonzero = saturn_nestor.sensitivity_from_backward(grid, agg="center")
    assert sens == pytest.approx(3.0e-9)
    assert n_nonzero == 2


def test_sample_cell_mean3x3_damps() -> None:
    conc = np.zeros((1, 41, 41))
    grid = _grid_covering_sources(conc)
    _, slat, slon, _ = saturn_nestor.SOURCE
    i, j = saturn_nestor.cell_index(grid, slat, slon)
    conc[0, i, j] = 9.0
    center = saturn_nestor.sample_cell(grid, slat, slon, agg="center")
    smooth = saturn_nestor.sample_cell(grid, slat, slon, agg="mean3x3")
    assert center[0] == pytest.approx(9.0)
    assert smooth[0] == pytest.approx(1.0)  # 9 spread over the 3×3 block


# ---------------------------------------------------------------------------
# Unit conversions (pinned to tijuana_dispersion.core constants)
# ---------------------------------------------------------------------------


def test_ppb_ugm3_round_trip_at_25c() -> None:
    """1.39 µg/m³ ≈ 1 ppb at 25 °C (test_core.py's pinned value)."""
    assert saturn_nestor.ugm3_to_ppb_h2s(1.39, 25.0) == pytest.approx(1.0, rel=0.01)
    assert saturn_nestor.ppb_to_ugm3_h2s(1.0, 25.0) == pytest.approx(1.3939, rel=1e-3)
    assert saturn_nestor.ugm3_to_ppb_h2s(
        saturn_nestor.ppb_to_ugm3_h2s(7.3, 12.0), 12.0
    ) == pytest.approx(7.3)


def test_ppb_conversion_temperature_monotonicity() -> None:
    """Cold air is denser: same µg/m³ → fewer ppb."""
    assert saturn_nestor.ugm3_to_ppb_h2s(1.0, 5.0) < saturn_nestor.ugm3_to_ppb_h2s(1.0, 35.0)


# ---------------------------------------------------------------------------
# Emission inference
# ---------------------------------------------------------------------------


def _frame(obs, sens, temp=25.0):
    return pd.DataFrame({"obs_ppb": obs, "sensitivity": sens, "temp_c": temp})


def test_infer_emissions_exact_recovery() -> None:
    """obs of 1 ppb at 25 °C over sensitivity 1.3939e-6 (g/m³)/(g/hr) → 1 g/hr."""
    c_gm3 = saturn_nestor.ppb_to_ugm3_h2s(1.0, 25.0) * 1e-6
    out = saturn_nestor.infer_emissions(_frame([1.0], [c_gm3]))
    assert out["flag"].tolist() == ["ok"]
    assert out["q_g_hr"].iloc[0] == pytest.approx(1.0)
    assert out["q_g_s"].iloc[0] == pytest.approx(1.0 / 3600.0)


def test_infer_emissions_flags() -> None:
    out = saturn_nestor.infer_emissions(
        _frame([1.0, np.nan, 1.0], [1e-12, 1e-6, 1e-6]), sensitivity_floor=1e-11
    )
    assert out["flag"].tolist() == ["below_floor", "no_obs", "ok"]
    assert np.isnan(out["q_g_hr"].iloc[0])  # Q undefined, NOT zero
    assert np.isnan(out["q_g_hr"].iloc[1])


def test_infer_emissions_qmax_flagged_but_kept() -> None:
    out = saturn_nestor.infer_emissions(
        _frame([1.0], [1e-13]), sensitivity_floor=1e-15, q_max_g_s=1000.0
    )
    assert out["flag"].tolist() == ["exceeds_qmax"]
    assert out["q_g_s"].iloc[0] > 1000.0  # value kept alongside the flag


# ---------------------------------------------------------------------------
# Scoring (parity with sobol.evaluate_sample's inline metric math)
# ---------------------------------------------------------------------------


def test_score_matches_sobol_inline_math() -> None:
    rng = np.random.default_rng(7)
    o = rng.uniform(0, 30, 24)
    p = o * 0.8 + rng.normal(0, 2, 24)
    got = saturn_nestor.score(o, p)
    assert got["rms"] == pytest.approx(float(np.sqrt(np.mean((o - p) ** 2))))
    assert got["corr"] == pytest.approx(float(np.corrcoef(o, p)[0, 1]))
    assert got["peak_ratio"] == pytest.approx(float(p.max() / (o.max() + 1e-6)))
    assert got["n_valid"] == 24


def test_score_too_few_valid_hours_is_neutral() -> None:
    got = saturn_nestor.score(
        np.array([1.0, 2.0, np.nan, np.nan, np.nan, np.nan]),
        np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0]),
    )
    assert np.isnan(got["rms"])
    assert got["corr"] == 0.0
    assert got["peak_ratio"] == 0.0


def test_score_flat_prediction_zero_corr() -> None:
    got = saturn_nestor.score(np.arange(6, dtype=float), np.full(6, 3.0))
    assert got["corr"] == 0.0


# ---------------------------------------------------------------------------
# Run tag + import contract
# ---------------------------------------------------------------------------


def test_run_tag_deterministic() -> None:
    tag = saturn_nestor.run_tag("2026-04-03", "2026-04-06", 12, "hrrr", run_date="2026-07-13")
    assert tag == "saturn_nestor_2026-04-03_2026-04-06_hb12_hrrr_2026-07-13"


def test_import_contract_assets_and_job() -> None:
    """The Dagster layer imports without HYSPLIT / met / the service extra."""
    from nrp.saturn_assets import saturn_nestor_job

    assert saturn_nestor_job.name == "saturn_nestor_job"


def test_hysplit_location_defs_include_saturn_job() -> None:
    from nrp.saturn_definitions import defs

    assert defs.get_job_def("saturn_nestor_job") is not None


def test_sobol_location_excludes_saturn_job() -> None:
    """The two code locations stay disjoint: the sobol location (plain
    worker image) must not carry the HYSPLIT job, and the hysplit location
    must not import the pymc/SALib-heavy pipeline module."""
    from nrp.dagster_pipeline import defs

    job_names = {j.name for j in defs.get_repository_def().get_all_jobs()}
    assert "saturn_nestor_job" not in job_names
