"""Experiment entry point.

Loads `config.yaml`, runs the experiment, writes outputs to `outputs/`,
updates RESULTS.md with key numbers (or leaves the human to write the
prose part).

Reproducible by: `uv run python run.py` from this folder.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

HERE = Path(__file__).parent
OUTPUTS = HERE / "outputs"


def load_config() -> dict:
    with (HERE / "config.yaml").open() as f:
        return yaml.safe_load(f)


def main() -> None:
    OUTPUTS.mkdir(exist_ok=True)
    config = load_config()
    log.info("loaded config: experiment=%s", config["experiment"]["name"])

    # === your experiment logic goes here ===
    # raise on missing data; never substitute fake values.

    # Example skeleton:
    #
    # from tijuana_dispersion import run_forward, ForwardRunRequest
    # from tijuana_emissions import EmissionsModel, EmissionParameters
    #
    # data = load_pinned_data(config["data"])  # raises if checksum mismatches
    # params = EmissionParameters(**config["emissions"])
    # model = EmissionsModel(params)
    # ...
    # results = ...
    # (OUTPUTS / "results.json").write_text(json.dumps(results, indent=2))

    log.info("done; outputs in %s", OUTPUTS)


if __name__ == "__main__":
    main()
