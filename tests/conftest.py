"""Pytest setup: make the repo root importable so `import nrp` works.

`tests/` is not a package and the repo isn't pip-installed, so pytest's
default import mode doesn't put the repo root on `sys.path`. The `nrp`
package (Dagster project, `[tool.dg] root_module = "nrp"`) lives at the
repo root; add it here so the NRP unit tests can import it. `tijuana_dispersion`
comes from the installed `service` extra and needs no path help.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
