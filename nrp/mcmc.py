"""MCMC calibration pipeline for H₂S dispersion parameters.

Uses Sobol sensitivity indices to inform prior distributions.
Samples posterior over 11 emission parameters via PyMC.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import arviz as az
import numpy as np
import pandas as pd
import pymc as pm

from nrp.sobol import PARAM_RANGES

# Sobol ST indices from the baseline (2026-03-13) Sobol run.
# Used to set prior widths: high-ST → tight, low-ST → wide.
SOBOL_BASELINE_ST = {
    "baseline_scale": 0.35,
    "substrate_threshold": 0.44,
    "diel_phase_hours": 0.77,
    "diel_amplitude_ppb": 0.06,
    "T_ref_c": 0.28,
    "Q10_warm": 0.04,
    "Q10_cool": 0.02,
    "f_arch_bay": 0.0,
    "f_arch_estuary": 0.15,
    "f_arch_channel": 0.01,
    "n_hours_window": 0.18,
}

# ST threshold: params with ST > this get tight priors.
ST_THRESHOLD = 0.10


@dataclass(frozen=True)
class PriorSpec:
    """Prior specification for one parameter."""

    name: str
    dist_type: str  # "normal", "uniform", "lognormal"
    mu: float | None = None  # mean (for normal, lognormal)
    sigma: float | None = None  # std (for normal, lognormal)
    low: float | None = None  # lower bound (for uniform)
    high: float | None = None  # upper bound (for uniform)
    bounds: tuple[float, float] | None = None  # (low, high) for truncated dists


def build_priors(
    sobol_indices: pd.DataFrame | None = None,
) -> dict[str, PriorSpec]:
    """Build prior specs based on Sobol ST indices.

    High-ST params get tight Normal priors centered on LHS best-fit.
    Low-ST params get wide Uniform priors over the feasible range.
    """
    priors = {}

    for param_name, (low, high) in PARAM_RANGES.items():
        st = SOBOL_BASELINE_ST.get(param_name, 0.0)
        mid = (low + high) / 2
        width = high - low

        if st > ST_THRESHOLD:
            # High-ST: tight Normal prior around midpoint
            sigma = 0.05 * width
            priors[param_name] = PriorSpec(
                name=param_name,
                dist_type="normal",
                mu=mid,
                sigma=sigma,
                bounds=(low, high),
            )
        else:
            # Low-ST: wide Uniform prior
            priors[param_name] = PriorSpec(
                name=param_name,
                dist_type="uniform",
                low=low,
                high=high,
            )

    return priors


def build_model(
    obs: dict[str, np.ndarray],
    forward_model_fn,
    priors: dict[str, PriorSpec],
    obs_sigma: float = 10.0,
) -> pm.Model:
    """Construct PyMC model for MCMC sampling.

    Args:
        obs: dict with keys like "rms__SAN YSIDRO", "peak_ratio__NESTOR - BES", etc.
             values are numpy arrays of observations
        forward_model_fn: callable(params_dict) -> dict with same keys as obs
        priors: dict of PriorSpec, one per parameter
        obs_sigma: observation noise std (ppb)

    Returns:
        PyMC Model ready for sampling
    """
    model = pm.Model()

    with model:
        # Define priors
        param_rvs = {}
        for param_name, spec in priors.items():
            if spec.dist_type == "normal":
                param_rvs[param_name] = pm.Normal(
                    param_name,
                    mu=spec.mu,
                    sigma=spec.sigma,
                    bounds=spec.bounds,
                )
            elif spec.dist_type == "uniform":
                param_rvs[param_name] = pm.Uniform(
                    param_name,
                    lower=spec.low,
                    upper=spec.high,
                )

        # Likelihood
        pred = pm.math.as_tensor_variable(
            forward_model_fn(param_rvs),
        )

        # Flatten observations to 1D for likelihood
        obs_flat = np.concatenate([v.flatten() for v in obs.values()])

        pm.Normal("likelihood", mu=pred, sigma=obs_sigma, observed=obs_flat)

    return model


def sample_posterior(
    model: pm.Model,
    n_chains: int = 9,
    n_draws: int = 5000,
    n_tune: int = 2500,
    seed: int = 42,
) -> az.InferenceData:
    """Sample posterior using NUTS sampler.

    Args:
        model: PyMC Model
        n_chains: number of parallel chains
        n_draws: total draws per chain (includes tune)
        n_tune: burn-in iterations per chain
        seed: random seed

    Returns:
        ArviZ InferenceData object with posterior samples + diagnostics
    """
    with model:
        idata = pm.sample(
            draws=n_draws - n_tune,
            tune=n_tune,
            chains=n_chains,
            cores=min(n_chains, 8),
            random_seed=seed,
            return_inferencedata=True,
            progressbar=True,
        )

    return idata


def diagnostics(idata: az.InferenceData) -> dict[str, Any]:
    """Compute convergence diagnostics.

    Args:
        idata: ArviZ InferenceData

    Returns:
        dict with Rhat, n_eff per param, plus overall convergence status
    """
    rhat = az.rhat(idata)
    eff_n = az.ess_bulk(idata)

    diag = {}
    for var_name in idata.posterior.data_vars:
        r = float(rhat[var_name].values.mean())
        n_e = float(eff_n[var_name].values.mean())
        diag[var_name] = {"rhat": r, "n_eff": n_e, "converged": r < 1.01}

    all_converged = all(d["converged"] for d in diag.values())
    diag["_summary"] = {
        "all_converged": all_converged,
        "n_params": len(diag) - 1,
        "max_rhat": max(d["rhat"] for d in diag.values() if d != diag["_summary"]),
    }

    return diag


def posterior_predictive_cv(
    idata: az.InferenceData,
    forward_model_fn,
    obs_holdout: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Evaluate posterior predictive on held-out data.

    Args:
        idata: posterior samples
        forward_model_fn: callable(params_dict) -> dict with same keys as obs
        obs_holdout: dict of held-out observations

    Returns:
        dict with RMSE per metric + overall mean RMSE
    """
    posterior = idata.posterior.to_dict()
    param_samples = {}

    for param_name in forward_model_fn.__code__.co_varnames:
        if param_name in posterior:
            param_samples[param_name] = posterior[param_name].values

    metrics = {}
    first_param_key = next(iter(param_samples.keys()))
    n_samples = len(param_samples[first_param_key])
    for metric_name, obs_vec in obs_holdout.items():
        preds = []
        for i in range(n_samples):
            params_i = {k: v[i] for k, v in param_samples.items()}
            pred_dict = forward_model_fn(params_i)
            preds.append(pred_dict.get(metric_name, np.nan))

        preds = np.array(preds)
        rmse = np.sqrt(np.mean((preds - obs_vec) ** 2))
        metrics[metric_name] = float(rmse)

    metrics["_mean_rmse"] = float(np.mean(list(metrics.values())))

    return metrics
