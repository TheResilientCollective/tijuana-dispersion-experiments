"""MCMC calibration pipeline for H₂S dispersion parameters.

Uses Sobol sensitivity indices to inform prior distributions.
Samples posterior over 11 emission parameters via PyMC.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import arviz as az
import numpy as np
import pandas as pd
import pymc as pm
import pytensor.tensor as pt
from pytensor.graph.basic import Apply
from pytensor.graph.op import Op

from nrp.sobol import PARAM_RANGES

# ST threshold: params with mean ST above this are treated as
# well-identified and get a weakly-informative (truncated Normal) prior;
# the rest get a wide Uniform over the feasible range. The likelihood
# still dominates — the Normal sigma is a sizeable fraction of the range.
ST_THRESHOLD = 0.10


def sobol_st_by_param(sobol_indices: pd.DataFrame | None) -> dict[str, float]:
    """Mean total-order ST per parameter from a Sobol indices table.

    Expects columns ``parameter`` and ``ST`` (as produced by
    ``sobol_aggregate``). Returns ``{}`` when no indices are supplied so
    callers fall back to non-informative priors.
    """
    if sobol_indices is None or len(sobol_indices) == 0:
        return {}
    return sobol_indices.groupby("parameter")["ST"].mean().to_dict()


@dataclass(frozen=True)
class PriorSpec:
    """Prior specification for one parameter."""

    name: str
    dist_type: str  # "normal" (truncated) or "uniform"
    mu: float | None = None  # mean (for normal)
    sigma: float | None = None  # std (for normal)
    low: float | None = None  # lower bound (for uniform)
    high: float | None = None  # upper bound (for uniform)
    bounds: tuple[float, float] | None = None  # (low, high) truncation for normal


def build_priors(
    sobol_indices: pd.DataFrame | None = None,
) -> dict[str, PriorSpec]:
    """Build prior specs, Sobol-informed when indices are supplied.

    High-ST params (well-identified) get a truncated Normal centred on
    the range midpoint; low-ST params get a wide Uniform over the
    feasible range. Parameter order follows :data:`PARAM_RANGES`. When
    ``sobol_indices`` is None every parameter falls back to Uniform.
    """
    st_by_param = sobol_st_by_param(sobol_indices)
    priors: dict[str, PriorSpec] = {}

    for param_name, (low, high) in PARAM_RANGES.items():
        st = float(st_by_param.get(param_name, 0.0))
        mid = (low + high) / 2
        width = high - low

        if st > ST_THRESHOLD:
            # Well-identified: weakly-informative truncated Normal. sigma
            # is 1/4 of the range so the data still drives the posterior.
            priors[param_name] = PriorSpec(
                name=param_name,
                dist_type="normal",
                mu=mid,
                sigma=0.25 * width,
                bounds=(low, high),
            )
        else:
            priors[param_name] = PriorSpec(
                name=param_name,
                dist_type="uniform",
                low=low,
                high=high,
            )

    return priors


def _gaussian_loglike(
    obs_flat: np.ndarray,
    forward_model_fn: Callable[[dict[str, float]], np.ndarray],
    param_order: list[str],
    obs_sigma: float,
) -> Callable[[np.ndarray], float]:
    """Build a scalar Gaussian log-likelihood over a concrete param vector.

    The returned closure maps a plain float vector (parameter values in
    ``param_order``) to ``log N(obs | forward_model(params), obs_sigma)``.
    It never touches PyTensor — it is the black box the Op wraps.
    """
    obs_flat = np.asarray(obs_flat, dtype="float64")
    norm_const = obs_flat.size * float(np.log(obs_sigma * np.sqrt(2.0 * np.pi)))

    def loglike(theta: np.ndarray) -> float:
        params = dict(zip(param_order, np.asarray(theta, dtype="float64"), strict=True))
        pred = np.asarray(forward_model_fn(params), dtype="float64")
        if pred.shape != obs_flat.shape or not np.all(np.isfinite(pred)):
            return -np.inf
        resid = obs_flat - pred
        return float(-0.5 * np.sum((resid / obs_sigma) ** 2) - norm_const)

    return loglike


class _LogLikeOp(Op):
    """PyTensor Op wrapping a black-box (numpy) scalar log-likelihood.

    The ``tijuana_dispersion`` forward model is opaque numpy, so it cannot
    live inside a PyMC symbolic graph. This Op evaluates it in ``perform``
    on concrete values and returns the scalar logp. No gradient is defined
    — SMC (``pm.sample_smc``) is gradient-free, so none is needed.
    """

    def __init__(self, loglike: Callable[[np.ndarray], float]) -> None:
        self._loglike = loglike

    def make_node(self, theta):
        theta = pt.as_tensor_variable(theta)
        return Apply(self, [theta], [pt.scalar(dtype="float64")])

    def perform(self, node, inputs, outputs):
        (theta,) = inputs
        outputs[0][0] = np.asarray(self._loglike(theta), dtype="float64")


def build_model(
    obs_flat: np.ndarray,
    forward_model_fn: Callable[[dict[str, float]], np.ndarray],
    priors: dict[str, PriorSpec],
    obs_sigma: float = 10.0,
) -> pm.Model:
    """Construct a PyMC model with a black-box (SMC-ready) likelihood.

    Args:
        obs_flat: 1D array of observed concentrations (valid entries only).
        forward_model_fn: callable(params_dict) -> 1D array aligned to
            ``obs_flat`` (same length/order). Runs the real dispersion model.
        priors: one PriorSpec per parameter; iteration order fixes the
            parameter vector order handed to ``forward_model_fn``.
        obs_sigma: observation noise std (ppb).

    Returns:
        PyMC Model ready for ``sample_posterior`` (SMC).
    """
    param_order = list(priors)
    loglike_op = _LogLikeOp(
        _gaussian_loglike(obs_flat, forward_model_fn, param_order, obs_sigma),
    )

    with pm.Model() as model:
        rvs = []
        for name in param_order:
            spec = priors[name]
            if spec.dist_type == "normal":
                low, high = spec.bounds
                rvs.append(
                    pm.TruncatedNormal(name, mu=spec.mu, sigma=spec.sigma, lower=low, upper=high),
                )
            else:
                rvs.append(pm.Uniform(name, lower=spec.low, upper=spec.high))
        theta = pt.stack(rvs)
        pm.Potential("likelihood", loglike_op(theta))

    return model


def sample_posterior(
    model: pm.Model,
    n_chains: int = 4,
    n_draws: int = 2000,
    n_tune: int = 0,  # unused for SMC; kept for call-site compatibility
    seed: int = 42,
    cores: int | None = None,
) -> az.InferenceData:
    """Sample the posterior with Sequential Monte Carlo.

    SMC is gradient-free, so it handles the black-box dispersion
    likelihood (which NUTS cannot). ``n_draws`` is the number of SMC
    particles per chain; ``n_tune`` is ignored (SMC has no separate
    tuning phase) and accepted only so existing call sites don't break.

    Returns ArviZ InferenceData with the posterior samples.
    """
    with model:
        idata = pm.sample_smc(
            draws=n_draws,
            chains=n_chains,
            cores=cores if cores is not None else min(n_chains, 8),
            random_seed=seed,
            progressbar=False,
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
    eff_n = az.ess(idata, method="bulk")

    diag: dict[str, Any] = {}
    for var_name in idata.posterior.data_vars:
        r = float(rhat[var_name].values.mean())
        n_e = float(eff_n[var_name].values.mean())
        diag[var_name] = {"rhat": r, "n_eff": n_e, "converged": r < 1.01}

    per_param = list(diag.values())
    diag["_summary"] = {
        "all_converged": all(d["converged"] for d in per_param),
        "n_params": len(per_param),
        "max_rhat": max((d["rhat"] for d in per_param), default=float("nan")),
    }

    return diag


def posterior_param_draws(
    idata: az.InferenceData,
    param_names: list[str],
    n_samples: int = 100,
) -> np.ndarray:
    """Thin the combined posterior to ``n_samples`` parameter vectors.

    Returns an ``(n, len(param_names))`` array of draws in ``param_names``
    order, evenly spaced across the stacked (chain, draw) samples.
    """
    post = idata.posterior.stack(sample=("chain", "draw"))
    n_total = int(post.sizes["sample"])
    k = min(n_samples, n_total)
    idx = np.linspace(0, n_total - 1, k).astype(int)
    return np.array(
        [[float(post[p].isel(sample=i)) for p in param_names] for i in idx],
        dtype="float64",
    )


def bound_railing(
    summary_df: pd.DataFrame,
    param_ranges: dict[str, tuple[float, float]],
    tol_frac: float = 0.02,
) -> list[dict[str, Any]]:
    """Flag parameters whose 94% HDI presses against a prior bound.

    A railing parameter means the data wants a value outside the box —
    the signal that a range should be widened. ``summary_df`` is an
    ``az.summary`` frame with a ``parameter`` column and ``hdi_3%`` /
    ``hdi_97%`` columns.
    """
    flagged: list[dict[str, Any]] = []
    for _, row in summary_df.iterrows():
        p = row["parameter"]
        if p not in param_ranges:
            continue
        low, high = param_ranges[p]
        span = high - low
        near_low = row["hdi_3%"] <= low + tol_frac * span
        near_high = row["hdi_97%"] >= high - tol_frac * span
        if near_low or near_high:
            flagged.append(
                {
                    "parameter": p,
                    "edge": "lower" if near_low else "upper",
                    "mean": float(row["mean"]),
                    "hdi_3%": float(row["hdi_3%"]),
                    "hdi_97%": float(row["hdi_97%"]),
                    "range": [low, high],
                },
            )
    return flagged


def predictive_skill(
    param_draws: np.ndarray,
    forward_predict: Callable[[np.ndarray], np.ndarray],
    obs_mat: np.ndarray,
    receptor_names: list[str],
) -> list[dict[str, Any]]:
    """Posterior-predictive skill per receptor.

    ``forward_predict`` maps one parameter vector to an ``(n_hours,
    n_receptors)`` prediction (e.g. ``sobol.predict_concentrations``
    bound to the window's drivers/met). ``obs_mat`` is the matching
    observed ``(n_hours, n_receptors)`` (NaN where missing). Returns, per
    receptor with enough obs: posterior-predictive RMSE and correlation
    of the mean, 94% interval coverage, and obs/pred means. Reused by
    both the MCMC report and leave-one-event-out CV.
    """
    preds = np.array([forward_predict(row) for row in param_draws])  # (K, H, R)
    out: list[dict[str, Any]] = []
    for r_idx, name in enumerate(receptor_names):
        valid = ~np.isnan(obs_mat[:, r_idx])
        if valid.sum() < 5:
            continue
        o = obs_mat[valid, r_idx]
        p = preds[:, valid, r_idx]
        mean = p.mean(axis=0)
        lo = np.percentile(p, 3, axis=0)
        hi = np.percentile(p, 97, axis=0)
        out.append(
            {
                "receptor": name,
                "n_obs": int(valid.sum()),
                "rmse": float(np.sqrt(np.mean((mean - o) ** 2))),
                "corr": float(np.corrcoef(mean, o)[0, 1]) if mean.std() > 0 else 0.0,
                "coverage_94": float(np.mean((o >= lo) & (o <= hi))),
                "obs_mean": float(o.mean()),
                "pred_mean": float(mean.mean()),
            },
        )
    return out
