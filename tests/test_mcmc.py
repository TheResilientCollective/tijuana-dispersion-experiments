"""Tests for the SMC calibration wiring in nrp.mcmc.

These exercise the black-box likelihood Op + pm.sample_smc path with a
synthetic (numpy) forward model, so they run without the image-only
``tijuana_dispersion`` service package. They verify the sampler actually
recovers known parameters through the black box — the property that the
placeholder implementation could never have.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nrp import mcmc
from nrp.sobol import PARAM_RANGES


def _normalized(params: dict[str, float]) -> np.ndarray:
    return np.array([(params[n] - lo) / (hi - lo) for n, (lo, hi) in PARAM_RANGES.items()])


def test_build_priors_uses_real_sobol_st():
    """High mean-ST params get truncated Normal; low-ST get Uniform."""
    idx = pd.DataFrame(
        [
            {"parameter": "diel_phase_hours", "metric": "m", "ST": 0.8},
            {"parameter": "f_arch_bay", "metric": "m", "ST": 0.0},
        ],
    )
    priors = mcmc.build_priors(sobol_indices=idx)
    assert priors["diel_phase_hours"].dist_type == "normal"
    assert priors["diel_phase_hours"].bounds == PARAM_RANGES["diel_phase_hours"]
    assert priors["f_arch_bay"].dist_type == "uniform"
    # No indices → everything falls back to Uniform.
    assert all(p.dist_type == "uniform" for p in mcmc.build_priors(None).values())


def test_smc_recovers_known_parameters():
    """SMC through the black-box Op recovers a known parameter vector."""
    rng = np.random.default_rng(0)
    d = len(PARAM_RANGES)
    matrix = rng.normal(size=(40, d))  # identifiable linear map on normalized params
    true = {n: lo + 0.3 * (hi - lo) for n, (lo, hi) in PARAM_RANGES.items()}

    def forward_model_fn(params: dict[str, float]) -> np.ndarray:
        return matrix @ _normalized(params)

    obs_flat = forward_model_fn(true)  # noiseless observations
    priors = mcmc.build_priors(sobol_indices=None)
    model = mcmc.build_model(obs_flat, forward_model_fn, priors, obs_sigma=0.05)
    idata = mcmc.sample_posterior(model, n_chains=2, n_draws=400, seed=42)

    diag = mcmc.diagnostics(idata)
    assert diag["_summary"]["n_params"] == d
    post = idata.posterior
    for name, (low, high) in PARAM_RANGES.items():
        rel_err = abs(float(post[name].mean()) - true[name]) / (high - low)
        assert rel_err < 0.1, f"{name}: normalized recovery error {rel_err:.3f}"


def test_forward_shape_mismatch_is_rejected():
    """A forward model returning the wrong shape yields -inf logp, not a crash."""
    priors = mcmc.build_priors(None)
    order = list(priors)
    loglike = mcmc._gaussian_loglike(
        np.zeros(5),
        lambda params: np.zeros(4),
        order,
        obs_sigma=1.0,
    )
    assert loglike(np.array([0.5] * len(order))) == float("-inf")
