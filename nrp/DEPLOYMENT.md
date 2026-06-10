# NRP deployment runbook — Sobol workload

Validated end-to-end on 2026-05-20/21. Do the steps in order; each
has a concrete check.

## 0. Readiness snapshot (updated 2026-05-21)

| Component | State | Evidence |
|---|---|---|
| Kube context | ✅ `nautilus` (NRP), ns `ucsd-center4health` | `kubectl config current-context` |
| RBAC: create Jobs in ns | ✅ `yes` | `kubectl auth can-i create jobs -n ucsd-center4health` |
| Object store | ✅ `https://oss.resilientservice.mooo.com`, bucket **`tj-calibration`** reachable | read-only `list_objects_v2` |
| Worker image | ✅ built, pushed, runs on-cluster | `gitlab-registry.nrp-nautilus.io/ucsd-center4health/nrp-worker` |
| `dagster-nrp` ServiceAccount + RBAC | ✅ created | `kubectl get sa dagster-nrp -n ucsd-center4health` |
| Dagster runtime (webserver + daemon) | ✅ Helm chart `dagster/dagster` v1.13.5 | `kubectl get pods -n ucsd-center4health` |
| Built-in PostgreSQL | ✅ managed by the Helm chart subchart | `dagster-postgresql-0` pod |
| Sobol backfill (100 chunks) | ✅ completed | backfill `nvntbbst` |

> Why a daemon is required: the assets use per-partition **multi-run**
> fan-out (one K8s Job per chunk — the correct NRP model). That is a
> Dagster *backfill*, which needs a running daemon. We deliberately did
> **not** use `BackfillPolicy.single_run()` (that would collapse 100
> chunks into one pod and defeat the parallelism).

## Prerequisites

- `kubectl` configured with the `nautilus` context
- `helm` (installed via `brew install helm`)
- `docker` with BuildKit support (Docker Desktop)
- `GITLAB_USER` and `GITLAB_TOKEN` env vars for `gitlab-registry.nrp-nautilus.io`
  (create token at `https://gitlab.nrp-nautilus.io/-/user_settings/personal_access_tokens`,
  scopes: `read_registry`, `write_registry`)
- `GH_TOKEN` for cloning the private `tijuana-dispersion` service repo

## 1. Build & push the worker image

The `service` extra (`tijuana-dispersion`) is a **private** git
dependency, so the build needs a GitHub token via a BuildKit secret
(never layered). Data is baked from `data/` — fetch it first.

**Important**: Build with `--platform linux/amd64` — NRP nodes are
amd64; building on Apple Silicon without this flag produces arm64
images that fail with `no match for platform in manifest`.

**Important**: `dagster-postgres` must be in `pyproject.toml`
dependencies. Without it, K8s run pods crash with
`Couldn't import module dagster_postgres.run_storage`.

```bash
# From the repo root:
source nrp/.env            # loads AWS keys, GITLAB creds, etc.
source nrp/env.sh           # sets TAG, logs into GitLab registry
# If TAG is stale from a previous session:
unset TAG DAGSTER_IMAGE && source nrp/env.sh

uv run python scripts/fetch_data.py --only modeldata_h2s_nofill

DOCKER_BUILDKIT=1 docker build -f nrp/Dockerfile \
  --platform linux/amd64 --target worker \
  --secret id=gh_token,env=GH_TOKEN -t "$TAG" .
docker push "$TAG"
export DAGSTER_IMAGE=$(docker inspect --format='{{index .RepoDigests 0}}' "$TAG")
echo "DAGSTER_IMAGE=$DAGSTER_IMAGE"
```

Checks:
- `docker run --rm --platform linux/amd64 "$TAG" python -c "import dagster_postgres, tijuana_dispersion, dagster, SALib; from nrp import sobol"` → clean.
- `docker run --rm --platform linux/amd64 "$TAG" python -c "from nrp import sobol; d=sobol.load_window(sobol.DEFAULT_PARQUET, sobol.DEFAULT_WINDOW); print(len(d))"` → non-zero (data baked).

Notes:
- Token-free sanity build (no service/data-dependent code): `docker build --target base …`.
- `env.sh` uses `${TAG:-…}` — if TAG is already set in the shell from a previous session,
  it won't pick up the new default. Always `unset TAG` before re-sourcing.
- The registry is `gitlab-registry.nrp-nautilus.io` (**not** `registry.nrp-nautilus.io`,
  which returns 404).

## 2. Namespace RBAC — `dagster-nrp` ServiceAccount

Committed manifest: **`nrp/k8s/rbac.yaml`** (SA + least-privilege Role
[jobs, pods, pods/log, secrets/configmaps] + RoleBinding).

```bash
kubectl apply -f nrp/k8s/rbac.yaml -n ucsd-center4health
kubectl get sa dagster-nrp -n ucsd-center4health           # exists
kubectl auth can-i create jobs -n ucsd-center4health \
  --as=system:serviceaccount:ucsd-center4health:dagster-nrp # yes
```

## 3. Secrets

Two secrets are needed. If sourcing `nrp/.env` first, shell variables
can be used directly (e.g. `"$AWS_ACCESS_KEY_ID"`).

```bash
source nrp/.env

# Object store + app credentials (all keys become env vars in worker pods)
kubectl create secret generic object-store-credentials -n ucsd-center4health \
  --from-literal=AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY_ID"            \
  --from-literal=AWS_SECRET_ACCESS_KEY="$AWS_SECRET_ACCESS_KEY"    \
  --from-literal=S3_ENDPOINT_URL="$S3_ENDPOINT_URL"                \
  --from-literal=AWS_DEFAULT_REGION="$AWS_DEFAULT_REGION"          \
  --from-literal=DAGSTER_S3_BUCKET="$DAGSTER_S3_BUCKET"            \
  --from-literal=SLACK_WEBHOOK_WATCH="$SLACK_WEBHOOK_WATCH"        \
  --from-literal=SLACK_WEBHOOK_CRITICAL="$SLACK_WEBHOOK_CRITICAL"  \
  --from-literal=NRP_NAMESPACE="$NRP_NAMESPACE"

# GitLab registry pull secret (needed by all pods pulling the worker image)
kubectl create secret docker-registry gitlab-registry-cred -n ucsd-center4health \
  --docker-server=gitlab-registry.nrp-nautilus.io \
  --docker-username="$GITLAB_USER" \
  --docker-password="$GITLAB_TOKEN"
```

Note: The Postgres password secret (`dagster-postgresql`) is auto-managed
by the Helm chart's built-in Bitnami PostgreSQL subchart — do not create
it manually.

## 4. Deploy Dagster (webserver + daemon) into the namespace

Committed values: **`nrp/k8s/dagster-values.yaml`**. Key settings
validated during the 2026-05-20 deployment:

- **Chart version**: `1.13.5` (pin this in the `--version` flag)
- **Built-in PostgreSQL**: `postgresql.enabled: true` — the chart
  provisions its own Bitnami PG. `global.postgresqlSecretName` must
  point to `dagster-postgresql` (the auto-created secret), not a
  manually created one.
- **Resource limits**: NRP's Gatekeeper policy requires CPU+memory
  requests and memory limits on all containers. All deployments have
  `100m`/`256Mi` requests and `500m`/`512Mi` limits.
- **imagePullSecrets**: set at both top-level and under
  `dagster-user-deployments` (the chart does not propagate them).
- **`serviceAccountName`** is NOT a valid key inside
  `runLauncher.config.k8sRunLauncher` in chart v1.13.5. The SA is set
  via the top-level `serviceAccount.name`.

```bash
helm repo add dagster https://dagster-io.github.io/helm && helm repo update

# PRE-FLIGHT — validate the values against the chart schema:
helm template dagster dagster/dagster -n ucsd-center4health --version 1.13.5 \
  -f nrp/k8s/dagster-values.yaml | kubectl apply --dry-run=client -f -

# Install / upgrade:
helm upgrade --install dagster dagster/dagster -n ucsd-center4health \
  --version 1.13.5 -f nrp/k8s/dagster-values.yaml
```

Checks:
- `kubectl get pods -n ucsd-center4health` → four pods, all `1/1 Running`:
  `dagster-daemon`, `dagster-dagster-webserver`, `dagster-dagster-user-deployments-nrp`,
  `dagster-postgresql-0`.
- Port-forward and verify the UI:
  ```bash
  kubectl port-forward svc/dagster-dagster-webserver 3000:80 -n ucsd-center4health
  # → http://127.0.0.1:3000 shows the asset graph with sobol_chunk_results (100 partitions)
  ```

## 5. Smoke test (one partition)

Materialize `sobol_chunk_results` partition `chunk_000` locally to
validate the pipeline end-to-end:

```bash
source nrp/.env && source nrp/env.sh
uv run dagster asset materialize -m nrp.definitions \
  --select sobol_chunk_results --partition chunk_000
```

This runs locally (multiprocess executor). Confirm `RUN_SUCCESS` in
the output and that the S3 IO manager initializes (`RESOURCE_INIT_SUCCESS`
for `s3_io`). If AWS keys are not set in the shell, the asset writes
to local filesystem instead — this is expected for a local smoke test.

## 6. Full submission

The `dg launch` CLI does **not** support multi-partition backfills
without `BackfillPolicy.single_run()`. Submit via the Dagster GraphQL
API instead, which delegates to the in-cluster daemon.

### 6a. Preview the plan (dry-run)

```bash
uv run python nrp/scripts/submit_sobol.py --dry-run
```

Defaults to `--n-base-samples 8192` (full scale). Prints the parameter
count, total samples (`N*(D+2) = 106,496`), partition layout (100
chunks, ~1,065 rows each), seed, and fit window — without touching
the cluster. **If N < 1024 the script prints a SMOKE warning** (the
postmortem fix: the May 2026 first NRP run was accidentally at N=16
because the script's previous default was a dev-sized value).

### 6b. Submit the backfill

Start a port-forward, then submit via the GraphQL API:

```bash
kubectl port-forward svc/dagster-dagster-webserver 3000:80 -n ucsd-center4health &
sleep 3
uv run python nrp/scripts/submit_sobol.py
kill %1 2>/dev/null
```

Defaults: `--n-base-samples 8192`, `--seed 42`, window from
`sobol.DEFAULT_WINDOW` (Mar 13–15 2026). Override flags:
`--n-base-samples`, `--seed`, `--window-start YYYY-MM-DD`,
`--window-end YYYY-MM-DD`. The run config is passed via the GraphQL
mutation so on-cluster runs use the requested params instead of
`SobolConfig`'s tiny local-dev default.

The script prints the backfill ID (e.g. `nvntbbst`) AND the exact
follow-up `dg launch` command to run after the chunks finish — copy
it; you'll need it in 6e.

### 6c. Monitor progress

**Quick kubectl check** (job-level):
```bash
kubectl get jobs -n ucsd-center4health --no-headers | awk '{print $2}' | sort | uniq -c
```

**Dagster UI**: port-forward and open `http://127.0.0.1:3000` →
Backfills tab → select the backfill ID.

Typical run: ~100 K8s Jobs, most complete in 50–90s, a few long-tail
partitions take up to ~25 min. Total wall-time ~30 min.

### 6d. Clean up failed jobs (if any)

```bash
kubectl delete jobs --field-selector status.successful=0 -n ucsd-center4health
```

### 6e. Materialise aggregator + post-analysis

After all 100 partitions of `sobol_chunk_results` complete, run the
follow-up command `submit_sobol.py` printed in 6b — it launches
**both** `sobol_aggregate` AND `sobol_post_analysis` in a single
run, with the same `(n, seed, window)` config so the archival tag
matches:

```bash
kubectl port-forward svc/dagster-dagster-webserver 3000:80 -n ucsd-center4health &
sleep 3
dg launch --assets sobol_aggregate,sobol_post_analysis \
  --config '{"ops":{"sobol_post_analysis":{"config":{"n_base_samples":8192,"seed":42,"window_start":"2026-03-13","window_end":"2026-03-16"}}}}'
kill %1 2>/dev/null
```

`sobol_post_analysis` computes convergence diagnostics (would have
caught the May 2026 smoke-as-real bug automatically), per-receptor
top-N, magnitude-vs-shape decomposition, interaction tables, and
window-specific dropout candidates. It writes the durable archive
described in 6f and surfaces the headline numbers in the Dagster UI
via `MaterializeResult` metadata.

### 6f. The S3 layout (two paths, on purpose)

| Path | Lifecycle | Contents |
|---|---|---|
| `s3://<bucket>/dagster/runs/sobol_aggregate` | **overwritten each run** (IO-manager pointer to "latest") | pickled `{"indices": [...records...]}` |
| `s3://<bucket>/dagster/runs/sobol_chunk_results/<chunk_NNN>` | overwritten each run | pickled chunk values |
| **`s3://<bucket>/runs/<tag>/`** | **durable, per-run** (written by `sobol_post_analysis`) | `sobol_indices.parquet`, `analysis.json`, `summary.md` |

The archive tag is deterministic: `{window_start}_{window_end}_N{n}_seed{seed}_{YYYY-MM-DD}` (e.g. `2026-03-13_2026-03-16_N8192_seed42_2026-05-22`). Multi-window / multi-seed studies coexist without overwriting.

### 6g. Retrieve results

```bash
source nrp/.env

# Latest run (IO-manager pointer):
uv run python nrp/scripts/fetch_sobol_results.py

# Specific archived snapshot:
uv run python nrp/scripts/fetch_sobol_results.py \
  --run-tag 2026-03-13_2026-03-16_N8192_seed42_2026-05-22

# → experiments/2026-05-15_sobol_full/output/sobol_indices.csv
```

S3 mode auto-detects when `DAGSTER_S3_BUCKET` + `S3_ENDPOINT_URL` +
AWS creds are all present. Pass `--force-local` to skip S3. Then
write up findings in `experiments/2026-05-15_sobol_full/RESULTS.md`.

### 6h. Bulk multi-window (one command, N windows sequential)

Submit a list of fit windows in one invocation. Each runs in
sequence: chunks backfill → poll → `sobol_aggregate_job` (aggregate +
post-analysis) → poll → next. **Sequential by design**: the IO
manager keys chunks by asset name only, so parallel windows would
race-overwrite each other; the durable per-run archive at
`s3://<bucket>/runs/<tag>/` preserves every window permanently.

Author a `windows.yaml` (any name; check it into the experiment dir):

```yaml
# experiments/<new-exp>/windows.yaml
windows:
  - { start: "2026-03-13", end: "2026-03-16", note: "advective baseline" }
  - { start: "2026-05-10", end: "2026-05-12", note: "calm-night Berry event" }
  - { start: "2026-02-08", end: "2026-02-11", note: "winter storm" }
```

Then:

```bash
kubectl port-forward svc/dagster-dagster-webserver 3000:80 -n ucsd-center4health &
sleep 3
# Dry-run first — prints the full plan, archive tags, no submission:
uv run python nrp/scripts/submit_sobol.py --windows-file windows.yaml --dry-run

# Live (~30 min per window at N=8192 × 100 chunks):
uv run python nrp/scripts/submit_sobol.py --windows-file windows.yaml
kill %1 2>/dev/null
```

Each window produces a distinct archive at
`s3://<bucket>/runs/{start}_{end}_N8192_seed42_{date}/`. The script
polls Dagster every `--poll-interval` (default 30 s); use
`--start-from N` to resume past a previously-completed window after a
failure; pass `--continue-on-error` to keep going past a failed
window. `--skip-aggregate` submits chunks only (for when you want to
intervene before the aggregate runs).

The end-of-run summary table lists every window with its terminal
status and archive tag — copy the tags into `fetch_sobol_results.py
--run-tag <tag>` to pull each result.

## 7. Lessons learned (2026-05-20/21 deployment)

- **Registry URL**: `gitlab-registry.nrp-nautilus.io`, not
  `registry.nrp-nautilus.io` (which 404s). The NRP docs confirm this.
- **Platform**: Always build with `--platform linux/amd64` on Apple
  Silicon. NRP nodes are amd64.
- **`dagster-postgres`**: Required in `pyproject.toml` dependencies.
  Without it, K8s run pods fail at startup trying to connect to the
  Dagster Postgres instance.
- **imagePullSecrets**: The GitLab registry requires authentication.
  Create a `docker-registry` secret and reference it in both
  top-level `imagePullSecrets` and `dagster-user-deployments.imagePullSecrets`.
- **Resource limits**: NRP enforces Gatekeeper policies. All containers
  must have CPU+memory requests and memory limits. CPU requests must
  not exceed CPU limits.
- **Postgres**: Use the chart's built-in Bitnami PostgreSQL
  (`postgresql.enabled: true`). Point `global.postgresqlSecretName`
  to `dagster-postgresql` (the auto-created secret name).
- **Backfill submission**: The `dg launch` CLI cannot submit
  multi-partition backfills. Use the GraphQL API via
  `nrp/scripts/_submit_backfill.py`.

## 8. Teardown

```bash
helm uninstall dagster -n ucsd-center4health
```

Removes the runtime; Jobs are owned by their runs and GC per Dagster
config. Artifacts in `s3://tj-calibration` persist (intentional —
that's the result store).
