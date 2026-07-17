"""Thin HYSPLIT subprocess runner (slim port of tj_h2s_prediction's
``HysplitRunner.run_control``).

Writes CONTROL/SETUP.CFG (+ optional extra files such as EMITIMES) into a
fresh per-run working directory, invokes the requested executable from
``$HYSPLIT_PATH`` (default ``/opt/hysplit/exec``, where the worker-hysplit
image stage installs the binaries) with that directory as cwd, and returns
the cdump path. On failure the tail of HYSPLIT's MESSAGE diagnostics file is
included in the raised error — that is where met-file problems surface
(e.g. ``metset: Bad value`` for a missing GDAS/HRRR file).

Kept separate from ``saturn_nestor.py`` so the science module stays
subprocess-free and CI-importable without the binary.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HYSPLIT_PATH = "/opt/hysplit/exec"


@dataclass
class HysplitRunResult:
    """Outcome of one CONTROL execution."""

    returncode: int
    workdir: Path
    cdump_path: Path
    message_tail: str


def _message_tail(workdir: Path, n_lines: int = 25) -> str:
    msg = workdir / "MESSAGE"
    if not msg.exists():
        return "(no MESSAGE file)"
    lines = msg.read_text(errors="replace").splitlines()
    return "\n".join(lines[-n_lines:])


def run_control(
    control_text: str,
    setup_text: str,
    workdir_root: Path | None = None,
    executable: str = "hycs_std",
    extra_files: dict[str, str] | None = None,
    timeout_seconds: int = 1800,
    output_file: str = "cdump",
) -> HysplitRunResult:
    """Execute one CONTROL under a fresh working directory.

    ``extra_files`` maps filename → content (e.g. ``{"EMITIMES": ...}``).
    Raises ``RuntimeError`` (with MESSAGE tail) on a non-zero exit or a
    missing/empty cdump, and ``FileNotFoundError`` if the executable is
    absent (i.e. running outside the worker-hysplit image).
    """
    hysplit_path = Path(os.getenv("HYSPLIT_PATH", DEFAULT_HYSPLIT_PATH))
    exe = hysplit_path / executable
    if not exe.exists():
        raise FileNotFoundError(
            f"HYSPLIT executable not found at {exe}. Run inside the worker-hysplit "
            "image (see nrp/Dockerfile) or set HYSPLIT_PATH.",
        )

    root = workdir_root or Path(os.getenv("HYSPLIT_WORKING_DIR", "/data/hysplit/work"))
    workdir = root / f"run_{uuid.uuid4().hex[:12]}"
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "CONTROL").write_text(control_text)
    (workdir / "SETUP.CFG").write_text(setup_text)
    for name, content in (extra_files or {}).items():
        (workdir / name).write_text(content)

    proc = subprocess.run(
        [str(exe)],
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    tail = _message_tail(workdir)
    cdump = workdir / output_file
    if proc.returncode != 0:
        raise RuntimeError(
            f"{executable} exited {proc.returncode} in {workdir}\n"
            f"stderr: {proc.stderr.strip()[:2000]}\nMESSAGE tail:\n{tail}",
        )
    if not cdump.exists() or cdump.stat().st_size == 0:
        raise RuntimeError(
            f"{executable} produced no {output_file} in {workdir}\nMESSAGE tail:\n{tail}",
        )
    return HysplitRunResult(
        returncode=proc.returncode,
        workdir=workdir,
        cdump_path=cdump,
        message_tail=tail,
    )
