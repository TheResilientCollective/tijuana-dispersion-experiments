# syntax=docker/dockerfile:1.7
# Worker image for Dagster-K8s NRP jobs.
# Built and pushed manually (or by CI with the GH token secret); the
# resulting digest is pinned in nrp/.env DAGSTER_IMAGE — never :latest.
#
# Build (BuildKit required for the --mount=type=secret line):
#   DOCKER_BUILDKIT=1 docker build -f nrp/Dockerfile \
#     --secret id=gh_token,env=GH_TOKEN \
#     -t gitlab-registry.nrp-nautilus.io/ucsd-center4health/nrp-worker:<tag> .
#   GH_TOKEN must read the (currently-private) tijuana-dispersion repo
#   so `--extra service` resolves; the token is mounted, never layered.
#
# Token-free local sanity build (deps + code only, no service extra):
#   docker build -f nrp/Dockerfile --target base -t nrp-worker:base .

FROM python:3.12-slim AS base

# System deps for scipy/numpy wheels, S3 client, and the git VCS
# dependency (tijuana-dispersion is a git+https requirement).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv for fast deterministic installs.
RUN pip install --no-cache-dir uv

# Base deps from the locked manifest (no dev, NO service extra). This
# stage is import-clean for the pure-science surface and is the
# token-free local build target. --no-install-project: the experiments
# repo is deliberately not a package (pyproject: packages=[],
# bypass-selection) — we install deps only and put the code on
# PYTHONPATH below, which also avoids needing the README in context.
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project

# uv installs into /app/.venv — make it the default interpreter so the
# container's `python` / Dagster's step entrypoint see the deps
# (without this, `python` is the bare system one: ModuleNotFoundError).
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Analysis + pipeline code.
COPY nrp/ ./nrp/
COPY emissions_research/ ./emissions_research/
COPY experiments/ ./experiments/

# Bake the H2S observations in (issue sobol_nrp.md: "the worker image
# bakes the data in or fetches it"). load_window() RAISES if absent —
# it never fabricates — so the data must be present in the build
# context (run scripts/fetch_data.py before building).
COPY data/ ./data/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Dagster overrides CMD when launching a specific run/step.
CMD ["dagster-daemon", "run"]

# ---- Full worker: base + the tijuana_dispersion service extra ------
# Separate stage so the heavy/private install is opt-in and the GH
# token is provided via a BuildKit secret (not persisted in any layer).
FROM base AS worker
COPY nrp/scripts/with_gh_auth.sh /tmp/with_gh_auth.sh
RUN --mount=type=secret,id=gh_token sh /tmp/with_gh_auth.sh && rm /tmp/with_gh_auth.sh

# ---- worker-hysplit: geodemichysplit + the nrp code/env -------------
# ONE image carries the licensed HYSPLIT: ghcr.io/center4health/
# geodemichysplit (built by GeoDemic CI from the registered v5.4.2
# tarball). This stage derives from it — geodemic docker + a layer with
# what the saturn_nestor workload needs — so no tarball ever lives here.
# The base already ships uv, /opt/hysplit, netcdf/proj/tini runtime libs,
# /data/hysplit/{work,meteo,output} dirs owned by the `geodemic` user,
# and HYSPLIT_WORKING_DIR/HYSPLIT_METEO_DIR env matching nrp defaults.
# It is PRIVATE: `docker login ghcr.io` with a GitHub token that has
# read:packages on center4health. Pin a digest via
#   --build-arg HYSPLIT_BASE=ghcr.io/center4health/geodemichysplit@sha256:…
# (The pre-derivation tarball/donor stages live in git history: b381d15.)
ARG HYSPLIT_BASE=ghcr.io/center4health/geodemichysplit:latest
FROM ${HYSPLIT_BASE} AS worker-hysplit
USER root
# git: needed for the private tijuana-dispersion VCS dep (base has none).
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /nrp
# The base is Python 3.13; this repo pins ==3.12.* — uv provisions a
# managed 3.12 for the /nrp venv (locked wheels are proven on 3.12/amd64).
RUN uv python install 3.12
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project
COPY nrp/scripts/with_gh_auth.sh /tmp/with_gh_auth.sh
RUN --mount=type=secret,id=gh_token sh /tmp/with_gh_auth.sh && rm /tmp/with_gh_auth.sh
COPY nrp/ ./nrp/
COPY emissions_research/ ./emissions_research/
COPY experiments/ ./experiments/
COPY data/ ./data/
RUN chown -R geodemic:geodemic /nrp && test -x /opt/hysplit/exec/hycs_std
# Front-run the geodemic app venv on PATH; HYSPLIT_PATH for hysplit_exec.
ENV VIRTUAL_ENV=/nrp/.venv \
    PATH="/nrp/.venv/bin:$PATH" \
    PYTHONPATH=/nrp \
    PYTHONUNBUFFERED=1 \
    HYSPLIT_PATH=/opt/hysplit/exec
USER geodemic
# Dagster overrides CMD when launching a specific run/step.
CMD ["dagster-daemon", "run"]
