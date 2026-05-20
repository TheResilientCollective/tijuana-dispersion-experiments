#!/usr/bin/env bash
# Source this file before any NRP deployment steps:
#   source nrp/env.sh
#
# Secrets (AWS keys, Postgres password, Slack webhooks) must be filled in
# manually — they are never committed. Everything else has a safe default
# derived from the repo or the cluster topology described in DEPLOYMENT.md.

# ---------------------------------------------------------------------------
# GitHub — needed for the BuildKit secret during docker build (§1)
# ---------------------------------------------------------------------------
export GH_TOKEN="${GH_TOKEN:-$(gh auth token 2>/dev/null)}"

# ---------------------------------------------------------------------------
# Worker image — set TAG before building, DAGSTER_IMAGE after pushing (§1)
# ---------------------------------------------------------------------------
export TAG="${TAG:-registry.nrp-nautilus.io/ucsd-center4health/nrp-worker:$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --short HEAD 2>/dev/null || echo dev)}"
# After `docker push "$TAG"` run:
#   export DAGSTER_IMAGE=$(docker inspect --format='{{index .RepoDigests 0}}' "$TAG")
export DAGSTER_IMAGE="${DAGSTER_IMAGE:-}"

# ---------------------------------------------------------------------------
# Object store (S3-compatible)
# ---------------------------------------------------------------------------
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-}"           # FILL IN
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-}"   # FILL IN
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-west-2}"
export S3_ENDPOINT_URL="${S3_ENDPOINT_URL:-https://oss.resilientservice.mooo.com}"
export DAGSTER_S3_BUCKET="${DAGSTER_S3_BUCKET:-tj-calibration}"

# ---------------------------------------------------------------------------
# Slack webhooks (reused from existing alert system)
# ---------------------------------------------------------------------------
export SLACK_WEBHOOK_WATCH="${SLACK_WEBHOOK_WATCH:-}"       # FILL IN — 30 ppb tier
export SLACK_WEBHOOK_CRITICAL="${SLACK_WEBHOOK_CRITICAL:-}" # FILL IN — 100 ppb tier

# ---------------------------------------------------------------------------
# Kubernetes / NRP
# ---------------------------------------------------------------------------
export NRP_NAMESPACE="${NRP_NAMESPACE:-ucsd-center4health}"

# ---------------------------------------------------------------------------
# Dagster local home (local dev only; overridden by Helm on-cluster)
# ---------------------------------------------------------------------------
_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DAGSTER_HOME="${DAGSTER_HOME:-${_REPO_ROOT}/dagster_home}"

# ---------------------------------------------------------------------------
# PostgreSQL (in-cluster; not used in local-file-based dev mode)
# ---------------------------------------------------------------------------
export DAGSTER_PG_USER="${DAGSTER_PG_USER:-dagster}"
export DAGSTER_PG_PASSWORD="${DAGSTER_PG_PASSWORD:-}"       # FILL IN
export DAGSTER_PG_HOST="${DAGSTER_PG_HOST:-dagster-postgres.ucsd-center4health.svc.cluster.local}"
export DAGSTER_PG_DB="${DAGSTER_PG_DB:-dagster}"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo "NRP env loaded — TAG=${TAG}"
echo "  DAGSTER_IMAGE=${DAGSTER_IMAGE:-<not set — fill in after docker push>}"
echo "  AWS_ACCESS_KEY_ID=${AWS_ACCESS_KEY_ID:-<not set>}"
echo "  DAGSTER_HOME=${DAGSTER_HOME}"
