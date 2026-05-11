# Worker image for Dagster-K8s NRP jobs.
# Built and pushed by the experiments-repo CI (or manually).
# Pinned in dagster_pipeline.py by digest, never :latest.

FROM python:3.12-slim

# System deps for scipy/numpy wheels and S3 client
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for fast deterministic deps
RUN pip install --no-cache-dir uv

# Copy and install dependencies (the experiments repo's lockfile)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

# Copy the package + analysis code
COPY nrp/ ./nrp/
COPY emissions_research/ ./emissions_research/
COPY experiments/ ./experiments/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Default command runs Dagster's K8s job entrypoint;
# Dagster overrides this when launching specific jobs.
CMD ["dagster-daemon", "run"]
