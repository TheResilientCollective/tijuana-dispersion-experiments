"""Saturn Blvd Bridge → NESTOR-BES back/forward H2S calculation — science core.

Single-source, single-receptor HYSPLIT workload:

1. **Backward**: one ``hycs_std`` run per observation hour (negative runtime,
   unit 1 g/hr release *at Nestor* for 1 h) → adjoint footprint. By
   source–receptor reciprocity the footprint value at the Saturn Blvd Bridge
   grid cell is the dilution sensitivity s(t) [(g/m³)/(g/hr)].
2. **Back-calculation**: ``Q(t) [g/hr] = C_obs(t)[g/m³] / s(t)``, guarded by a
   sensitivity floor (footprint missed the Saturn cell → NaN + flag) and a Q
   ceiling.
3. **Forward**: ``hycs_std`` from Saturn only — constant prior (5 g/s, the
   ``saturn_blvd_bridge`` q_prior in tj_h2s_prediction's source_geometry.toml)
   and the inferred Q(t) via EMITIMES — sampled at the Nestor cell and scored
   against observations with the same metric kinds as ``sobol.evaluate_sample``
   (rms / corr / peak_ratio).

This module is the pure, framework-agnostic science: no Dagster, no HYSPLIT
binary, no ``service`` extra. It is imported by ``nrp/saturn_assets.py`` (the
Dagster layer) and unit-tested in CI without any of those. Subprocess execution
lives in ``nrp/hysplit_exec.py``; met acquisition in ``nrp/metfetch.py``.

Hard rule (AGENTS.md): never fabricate data. If the H2S parquet is missing the
loader raises — it does not synthesise observations.

Known deviations from the reference CONTROL writer
(tj_h2s_prediction/.../dispersion/hysplit_controls.py), both deliberate:
- the concentration-grid block is written as CENTER / SPACING / SPAN degrees
  (what HYSPLIT's CONTROL expects), not SW-corner + cell counts;
- emission rates in CONTROL/EMITIMES are g/hr (the CONTROL field is a
  per-hour rate), so g/s values are multiplied by 3600.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import sobol

# ---------------------------------------------------------------------------
# Physical setup
# ---------------------------------------------------------------------------

#: (name, lat, lon, release height m AGL). Receptor release height 10 m — the
#: monitor intake; source at 2 m — water-surface off-gassing at the crossing.
RECEPTOR: tuple[str, float, float, float] = ("NESTOR - BES", 32.567097, -117.090656, 10.0)
SOURCE: tuple[str, float, float, float] = ("Saturn Blvd Bridge", 32.559383, -117.092992, 2.0)

#: Default window: the Apr 4 2026 15:00 local peak that the emission inversion
#: localised to ~415 m of Saturn Blvd Bridge. [start, end) local dates, like
#: sobol.DEFAULT_WINDOW.
DEFAULT_WINDOW: tuple[str, str] = ("2026-04-03", "2026-04-06")

#: Constant prior emission rate for the forward baseline run
#: (source_geometry.toml [sources.saturn_blvd_bridge] q_prior).
PRIOR_Q_G_S = 5.0

#: Concentration grid, both directions: centred on the Saturn↔Nestor midpoint,
#: 0.005° cells, 0.20° span (40×40) — Saturn and Nestor land in distinct cells.
GRID = {
    "center_lat": 32.5632,
    "center_lon": -117.0918,
    "spacing_deg": 0.005,
    "span_deg": 0.20,
    "sample_height_m": 10.0,
}

#: H2S molar mass (g/mol) and molar volume at 25 °C / 1 atm (L/mol) — the same
#: constants as tijuana_dispersion.core.ugm3_to_ppb_h2s (implemented locally so
#: this workload needs no ``service`` extra): 1 ppb = 34.08/24.45 ≈ 1.394 µg/m³.
H2S_MOLAR_MASS = 34.08
MOLAR_VOLUME_25C = 24.45

DEFAULT_PARQUET = sobol.DEFAULT_PARQUET

TZ_LOCAL = "America/Los_Angeles"


def setup_cfg(numpar: int = 2500, use_emitimes: bool = False) -> str:
    """SETUP.CFG namelist — stable-nocturnal-BL tuning from the tj reference
    (Beljaars-Holtslag turbulence, shallow vertical scale), with NUMPAR raised
    for single-cell sampling and EFILE added for time-varying emissions.
    """
    efile = "  EFILE   = 'EMITIMES',\n" if use_emitimes else ""
    return (
        "&SETUP\n"
        "  KMSL    = 0,\n"
        "  NINIT   = 1,\n"
        "  DELT    = 0.0,\n"
        "  KBLT    = 1,\n"
        "  KZMIX   = 1,\n"
        "  TVMIX   = 1.0,\n"
        "  KHMAX   = 9999,\n"
        f"  NUMPAR  = {int(numpar)},\n"
        "  QCYCLE  = 1.0,\n"
        "  INITD   = 0,\n"
        "  ICHEM   = 0,\n"
        "  KDEF    = 0,\n"
        "  HSCALE  = 10000.0,\n"
        "  VSCALE  = 100.0,\n"
        "  NCYCL   = 1,\n"
        "  NDUMP   = 0,\n"
        "  NSTR    = 0,\n"
        f"{efile}"
        "/\n"
    )


# ---------------------------------------------------------------------------
# CONTROL / EMITIMES generation
# ---------------------------------------------------------------------------


def _hysplit_time(ts: pd.Timestamp) -> str:
    """``yy mm dd hh`` (2-digit year), the CONTROL start-time encoding."""
    return ts.strftime("%y %m %d %H")


def _conc_grid_lines(output_file: str) -> list[str]:
    """Concentration-grid + sampling block shared by both directions.

    CENTER / SPACING / SPAN encoding (NOT the reference writer's SW-corner +
    cell-count encoding, which is not what CONTROL expects). Zero sampling
    start/stop = whole run; ``00 1 00`` = 1-hour averaging bins.
    """
    g = GRID
    return [
        "1",
        f"{g['center_lat']:.4f} {g['center_lon']:.4f}",
        f"{g['spacing_deg']:.3f} {g['spacing_deg']:.3f}",
        f"{g['span_deg']:.2f} {g['span_deg']:.2f}",
        "./",
        output_file,
        "1",
        f"{g['sample_height_m']:.0f}",
        "00 00 00 00 00",
        "00 00 00 00 00",
        "00 1 00",
    ]


def _deposition_lines() -> list[str]:
    """Gas, no deposition (H2S photolysis/deposition negligible at this scale)."""
    return [
        "1",
        "0.0 0.0 0.0",
        "0.0 0.0 0.0 0.0 0.0",
        "0.0 0.0 0.0",
        "0.0",
        "0.0",
    ]


def _met_lines(met_dir: str, met_files: list[str]) -> list[str]:
    if not met_files:
        raise ValueError("CONTROL needs at least one met file")
    d = met_dir if met_dir.endswith("/") else met_dir + "/"
    lines = [str(len(met_files))]
    for name in met_files:
        lines.extend([d, name])
    return lines


def write_backward_control(
    obs_hour_utc: pd.Timestamp,
    hours_back: int,
    met_dir: str,
    met_files: list[str],
    output_file: str = "cdump",
) -> str:
    """Backward (adjoint footprint) CONTROL for one observation hour.

    Unit 1 g/hr release at the NESTOR receptor for exactly the 1-hour
    observation averaging period, integrated ``hours_back`` hours backward.
    """
    _, lat, lon, agl = RECEPTOR
    lines = [
        _hysplit_time(obs_hour_utc),
        "1",
        f"{lat:.6f} {lon:.6f} {agl:.1f}",
        str(-int(hours_back)),
        "0",
        "10000.0",
        *_met_lines(met_dir, met_files),
        "1",
        "H2S",
        "1.0",
        "1.0",
        f"{_hysplit_time(obs_hour_utc)} 00",
        *_conc_grid_lines(output_file),
        *_deposition_lines(),
    ]
    return "\n".join(lines) + "\n"


def write_forward_control(
    start_utc: pd.Timestamp,
    run_hours: int,
    q_g_hr: float,
    met_dir: str,
    met_files: list[str],
    use_emitimes: bool = False,
    output_file: str = "cdump",
) -> str:
    """Forward dispersion CONTROL from the Saturn Blvd Bridge source only.

    ``q_g_hr`` is the constant per-hour emission rate (the CONTROL rate field
    is g/hr — pass ``q_g_s * 3600``). With ``use_emitimes`` the CONTROL rate
    and duration are zeroed and rates come from the EMITIMES file (SETUP.CFG
    must carry ``EFILE = 'EMITIMES',``).
    """
    _, lat, lon, agl = SOURCE
    rate = 0.0 if use_emitimes else float(q_g_hr)
    duration = 0.0 if use_emitimes else float(run_hours)
    lines = [
        _hysplit_time(start_utc),
        "1",
        f"{lat:.6f} {lon:.6f} {agl:.1f}",
        str(int(run_hours)),
        "0",
        "10000.0",
        *_met_lines(met_dir, met_files),
        "1",
        "H2S",
        f"{rate:.4f}",
        f"{duration:.1f}",
        f"{_hysplit_time(start_utc)} 00",
        *_conc_grid_lines(output_file),
        *_deposition_lines(),
    ]
    return "\n".join(lines) + "\n"


def write_emitimes(q_series_g_hr: pd.Series) -> str:
    """EMITIMES with one 1-hour record per hour at the Saturn source.

    ``q_series_g_hr`` is indexed by naive-UTC hourly timestamps; NaN hours
    are written as 0-rate records so the emission timeline stays contiguous.
    Format per the HYSPLIT User's Guide: two informational header lines, one
    cycle header ``YYYY MM DD HH DDDD #records`` covering the whole series,
    then ``YYYY MM DD HH MM DDHH LAT LON HGT RATE(g/hr) AREA HEAT`` records.
    """
    if q_series_g_hr.empty:
        raise ValueError("EMITIMES needs at least one hourly rate")
    idx = q_series_g_hr.index
    _, lat, lon, agl = SOURCE
    n = len(q_series_g_hr)
    first = idx[0]
    cycle_hours = int((idx[-1] - first) / pd.Timedelta(hours=1)) + 1
    lines = [
        "YYYY MM DD HH    DURATION(hhhh) #RECORDS",
        "YYYY MM DD HH MM DURATION(hhmm) LAT LON HGT(m) RATE(g/hr) AREA(m2) HEAT(w)",
        f"{first.strftime('%Y %m %d %H')} {cycle_hours:04d} {n}",
    ]
    for ts, q in q_series_g_hr.items():
        rate = 0.0 if pd.isna(q) else float(q)
        lines.append(
            f"{ts.strftime('%Y %m %d %H %M')} 0100 "
            f"{lat:.6f} {lon:.6f} {agl:.1f} {rate:.4f} 0.0 0.0",
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# cdump parsing
# ---------------------------------------------------------------------------


@dataclass
class CdumpGrid:
    """Per-sampling-period concentration grids from a HYSPLIT binary cdump.

    ``conc[t, i, j]`` is the bin-average concentration (mass/m³ per the run's
    emission units) at ``lats[i]``/``lons[j]`` for the sampling period ending
    at ``times[t]`` (naive UTC). First pollutant, first level.
    """

    times: list[pd.Timestamp]
    lats: np.ndarray
    lons: np.ndarray
    conc: np.ndarray


def _read_record(f) -> bytes | None:
    """One big-endian Fortran sequential record ([4-byte size][payload][size])."""
    hdr = f.read(4)
    if len(hdr) < 4:
        return None
    size = struct.unpack(">i", hdr)[0]
    data = f.read(size)
    if len(data) < size:
        raise ValueError("cdump truncated mid-record")
    f.read(4)
    return data


def parse_cdump(path: Path | str) -> CdumpGrid:
    """Parse a HYSPLIT binary cdump into per-period grids.

    Extends the GeoDemic ``_parse_cdump`` reference (which returned a
    time-mean array without axes): the grid-definition record is fully
    unpacked (spacing + SW corner → real lat/lon axes) and every sampling
    period is kept, so per-hour sensitivities can be extracted. Handles
    packing flag 0 (dense float32) and 1 (sparse (lon_idx, lat_idx, value)
    triples, 1-based).
    """
    with open(path, "rb") as f:
        r1 = _read_record(f)
        if not r1:
            raise ValueError("Empty cdump file")
        r1_fields = struct.unpack(">4siiiiiii", r1[:32])
        n_start_locs, packing = r1_fields[6], r1_fields[7]

        for _ in range(n_start_locs):
            if _read_record(f) is None:
                raise ValueError("cdump truncated at release-location records")

        r3 = _read_record(f)
        if r3 is None:
            raise ValueError("cdump truncated at grid definition record")
        nlat, nlon, dlat, dlon, clat, clon = struct.unpack(">iiffff", r3[:24])

        r4 = _read_record(f)
        if r4 is None:
            raise ValueError("cdump truncated at vertical levels record")
        nvert = struct.unpack(">i", r4[:4])[0]

        r5 = _read_record(f)
        if r5 is None:
            raise ValueError("cdump truncated at pollutant names record")
        ncomp = struct.unpack(">i", r5[:4])[0]

        times: list[pd.Timestamp] = []
        grids: list[np.ndarray] = []
        while True:
            r_start = _read_record(f)
            if r_start is None:
                break
            r_stop = _read_record(f)
            if r_stop is None:
                raise ValueError("cdump truncated at sampling stop record")
            yr, mo, da, hr, mn = struct.unpack(">iiiii", r_stop[:20])
            yr += 2000 if yr < 70 else (1900 if yr < 100 else 0)
            times.append(pd.Timestamp(year=yr, month=mo, day=da, hour=hr, minute=mn))

            # First pollutant, first level only (this workload writes 1×1);
            # remaining component/level records in the period are skipped.
            period_grid: np.ndarray | None = None
            for comp_idx in range(ncomp * nvert):
                r_conc = _read_record(f)
                if r_conc is None:
                    raise ValueError("cdump truncated at concentration record")
                if comp_idx > 0:
                    continue
                if packing == 0:
                    npts = nlat * nlon
                    vals = struct.unpack(f">{npts}f", r_conc[8 : 8 + npts * 4])
                    period_grid = np.array(vals, dtype=np.float32).reshape(nlat, nlon)
                elif packing == 1:
                    nnz = struct.unpack(">i", r_conc[8:12])[0]
                    arr = np.zeros((nlat, nlon), dtype=np.float32)
                    off = 12
                    for _ in range(nnz):
                        lon_i, lat_i = struct.unpack(">hh", r_conc[off : off + 4])
                        (val,) = struct.unpack(">f", r_conc[off + 4 : off + 8])
                        off += 8
                        arr[lat_i - 1, lon_i - 1] = val
                    period_grid = arr
                else:
                    raise ValueError(f"Unsupported cdump packing flag {packing}")
            if period_grid is None:
                raise ValueError("cdump sampling period carried no concentration record")
            grids.append(period_grid)

    if not grids:
        raise ValueError("No concentration data in cdump")
    return CdumpGrid(
        times=times,
        lats=clat + np.arange(nlat) * dlat,
        lons=clon + np.arange(nlon) * dlon,
        conc=np.stack(grids),
    )


def cell_index(grid: CdumpGrid, lat: float, lon: float) -> tuple[int, int]:
    """Nearest grid cell (lat_idx, lon_idx) to a point; raises if the point is
    outside the grid by more than one cell (a config error, not a data gap)."""
    i = int(np.argmin(np.abs(grid.lats - lat)))
    j = int(np.argmin(np.abs(grid.lons - lon)))
    dlat = float(np.abs(grid.lats[i] - lat))
    dlon = float(np.abs(grid.lons[j] - lon))
    step = float(grid.lats[1] - grid.lats[0]) if len(grid.lats) > 1 else 1.0
    if dlat > 1.5 * step or dlon > 1.5 * step:
        raise ValueError(
            f"Point ({lat}, {lon}) lies outside the cdump grid "
            f"(nearest cell {grid.lats[i]:.4f}, {grid.lons[j]:.4f})",
        )
    return i, j


def sample_cell(grid: CdumpGrid, lat: float, lon: float, agg: str = "mean3x3") -> np.ndarray:
    """Per-period concentration at a point: ``center`` cell or the ``mean3x3``
    neighbourhood mean (damps particle-count noise in 0.005° cells)."""
    i, j = cell_index(grid, lat, lon)
    if agg == "center":
        return grid.conc[:, i, j].astype(float)
    if agg == "mean3x3":
        i0, i1 = max(i - 1, 0), min(i + 2, grid.conc.shape[1])
        j0, j1 = max(j - 1, 0), min(j + 2, grid.conc.shape[2])
        return grid.conc[:, i0:i1, j0:j1].mean(axis=(1, 2)).astype(float)
    raise ValueError(f"Unknown cell aggregation {agg!r} (use 'center' or 'mean3x3')")


def sensitivity_from_backward(grid: CdumpGrid, agg: str = "mean3x3") -> tuple[float, int]:
    """Dilution sensitivity s(t) at the Saturn cell from one backward run.

    Sum of the per-hour-bin footprint values at the source cell, in
    (g/m³)/(g/hr): under the constant-Q-over-the-window assumption,
    ``C(receptor, t) = Q · Σ_bins footprint(Saturn, bin)``. Also returns the
    count of non-zero bins (0 → the footprint never touched the source cell).
    """
    _, lat, lon, _ = SOURCE
    series = sample_cell(grid, lat, lon, agg=agg)
    return float(series.sum()), int((series > 0).sum())


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------


def ppb_to_ugm3_h2s(ppb: float, temperature_c: float = 25.0) -> float:
    """H2S ppb → µg/m³ (ideal gas; same constants as tijuana_dispersion.core)."""
    molar_volume = MOLAR_VOLUME_25C * (273.15 + temperature_c) / 298.15
    return ppb * H2S_MOLAR_MASS / molar_volume


def ugm3_to_ppb_h2s(ugm3: float, temperature_c: float = 25.0) -> float:
    """H2S µg/m³ → ppb (inverse of :func:`ppb_to_ugm3_h2s`)."""
    molar_volume = MOLAR_VOLUME_25C * (273.15 + temperature_c) / 298.15
    return ugm3 * molar_volume / H2S_MOLAR_MASS


# ---------------------------------------------------------------------------
# Back-calculation + scoring
# ---------------------------------------------------------------------------


def infer_emissions(
    frame: pd.DataFrame,
    sensitivity_floor: float = 1e-11,
    q_max_g_s: float = 1000.0,
) -> pd.DataFrame:
    """Back-calculate the Saturn emission rate from observed Nestor H2S.

    ``frame`` needs columns ``obs_ppb``, ``sensitivity`` ((g/m³)/(g/hr)) and
    optionally ``temp_c`` (25 °C fallback). Adds ``q_g_hr``, ``q_g_s`` and a
    ``flag`` column: ``ok`` | ``no_obs`` | ``below_floor`` (footprint missed
    the source cell — Q undefined, NOT zero) | ``exceeds_qmax`` (kept, flagged;
    physically implausible, usually a near-floor sensitivity).
    """
    out = frame.copy()
    temp = out["temp_c"] if "temp_c" in out.columns else pd.Series(25.0, index=out.index)
    temp = temp.fillna(25.0)
    obs_gm3 = pd.Series(
        [
            ppb_to_ugm3_h2s(o, t) * 1e-6 if pd.notna(o) else np.nan
            for o, t in zip(out["obs_ppb"], temp, strict=True)
        ],
        index=out.index,
    )
    q_g_hr = pd.Series(np.nan, index=out.index)
    flags = []
    for idx in out.index:
        if pd.isna(out.at[idx, "obs_ppb"]):
            flags.append("no_obs")
            continue
        s = out.at[idx, "sensitivity"]
        if pd.isna(s) or s < sensitivity_floor:
            flags.append("below_floor")
            continue
        q = obs_gm3.at[idx] / s
        q_g_hr.at[idx] = q
        flags.append("exceeds_qmax" if q / 3600.0 > q_max_g_s else "ok")
    out["q_g_hr"] = q_g_hr
    out["q_g_s"] = q_g_hr / 3600.0
    out["flag"] = flags
    return out


def score(obs_ppb: np.ndarray, pred_ppb: np.ndarray) -> dict[str, float]:
    """rms / corr / peak_ratio — identical math to ``sobol.evaluate_sample``
    (≥5 jointly-valid hours; corr 0.0 for a flat prediction)."""
    obs = np.asarray(obs_ppb, dtype=float)
    pred = np.asarray(pred_ppb, dtype=float)
    valid = ~np.isnan(obs) & ~np.isnan(pred)
    if valid.sum() < 5:
        return {"rms": float("nan"), "corr": 0.0, "peak_ratio": 0.0, "n_valid": int(valid.sum())}
    o, p = obs[valid], pred[valid]
    return {
        "rms": float(np.sqrt(np.mean((o - p) ** 2))),
        "corr": float(np.corrcoef(o, p)[0, 1]) if p.std() > 0 else 0.0,
        "peak_ratio": float(p.max() / (o.max() + 1e-6)),
        "n_valid": int(valid.sum()),
    }


# ---------------------------------------------------------------------------
# Observations + run tag
# ---------------------------------------------------------------------------


def load_nestor_obs(parquet_path: Path, window: tuple[str, str]) -> pd.DataFrame:
    """Hourly NESTOR-BES observations for the window.

    Reuses ``sobol.load_window`` (raises if the parquet is missing — never
    fabricates) and filters to the NESTOR record. Columns: ``hour`` (tz-aware
    local, America/Los_Angeles), ``hour_utc`` (naive UTC — the CONTROL/cdump
    time frame), ``obs_ppb``, ``temp_c``, ``wind_speed_ms``, ``wind_dir_deg``.
    """
    df = sobol.load_window(parquet_path, window)
    nestor = df[df["site_name"] == RECEPTOR[0]].sort_values("hour").reset_index(drop=True)
    if nestor.empty:
        raise ValueError(f"No {RECEPTOR[0]} rows in window {window}")
    return pd.DataFrame(
        {
            "hour": nestor["hour"],
            "hour_utc": nestor["hour"].dt.tz_convert("UTC").dt.tz_localize(None),
            "obs_ppb": nestor["H2S"],
            "temp_c": nestor["temperature_2m"],
            "wind_speed_ms": nestor["wind_speed_10m"],
            "wind_dir_deg": nestor["wind_direction_10m"],
        },
    )


def run_tag(
    window_start: str,
    window_end: str,
    hours_back: int,
    met_source: str,
    run_date: str | None = None,
) -> str:
    """Deterministic archival tag, mirroring ``sobol.run_tag``:
    ``saturn_nestor_{start}_{end}_hb{hours_back}_{met}_{date}``."""
    if run_date is None:
        from datetime import UTC, datetime

        run_date = datetime.now(UTC).date().isoformat()
    return f"saturn_nestor_{window_start}_{window_end}_hb{hours_back}_{met_source}_{run_date}"
