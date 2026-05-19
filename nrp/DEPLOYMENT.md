# NRP deployment runbook — Sobol workload

Status of the moving parts, established by probing on 2026-05-18
(not assumed). Do the steps in order; each has a concrete check.

## 0. Readiness snapshot

| Component | State | Evidence |
|---|---|---|
| Kube context | ✅ `nautilus` (NRP), ns `ucsd-center4health` | `kubectl config current-context` |
| RBAC: create Jobs in ns | ✅ `yes` | `kubectl auth can-i create jobs -n ucsd-center4health` |
| Object store | ✅ `https://oss.resilientservice.mooo.com`, bucket **`tj-calibration`** reachable, creds in `nrp/.env` valid | read-only `list_objects_v2` |
| Worker image | ✅ builds & runs a real chunk end-to-end (after the Dockerfile fixes in this PR) | local `docker build` + in-container `evaluate_sample` |
| Worker image pushed to a registry NRP can pull | ❌ not done | `DAGSTER_IMAGE` digest must be set in `nrp/.env` |
| Dagster runtime in the namespace (webserver + **daemon**) | ❌ **none** | `kubectl get pods -n ucsd-center4health` → no resources |
| `dagster-nrp` ServiceAccount + RBAC | ❌ `NotFound` | `kubectl get sa dagster-nrp -n …` |

**The only hard blockers are the last three** — all deployment/provisioning,
none code. The pipeline is implemented, CI-green (PR #5), and validated
locally end-to-end (100 chunks → aggregate).

> Why a daemon is required: the assets use per-partition **multi-run**
> fan-out (one K8s Job per chunk — the correct NRP model). That is a
> Dagster *backfill*, which needs a running daemon. We deliberately did
> **not** use `BackfillPolicy.single_run()` (that would collapse 100
> chunks into one pod and defeat the parallelism).

## 1. Build & push the worker image

The `service` extra (`tijuana-dispersion`) is a **private** git
dependency, so the build needs a GitHub token via a BuildKit secret
(never layered). Data is baked from `data/` — fetch it first.

```bash
uv run python scripts/fetch_data.py --only modeldata_h2s_nofill   # ensure data/ present
export GH_TOKEN=$(gh auth token)          # read access to the private service repo
TAG=registry.nrp-nautilus.io/ucsd-center4health/nrp-worker:$(git rev-parse --short HEAD)

DOCKER_BUILDKIT=1 docker build -f nrp/Dockerfile --target worker \
  --secret id=gh_token,env=GH_TOKEN -t "$TAG" .
docker push "$TAG"
DIGEST=$(docker inspect --format='{{index .RepoDigests 0}}' "$TAG")
echo "DAGSTER_IMAGE=$DIGEST"             # put this (digest-pinned) in nrp/.env
```

Checks (all pass locally with this PR's Dockerfile):
- `docker run --rm "$TAG" python -c "import tijuana_dispersion, dagster, SALib; from nrp import sobol"` → clean.
- `docker run --rm "$TAG" python -c "from nrp import sobol; d=sobol.load_window(sobol.DEFAULT_PARQUET, sobol.DEFAULT_WINDOW); print(len(d))"` → non-zero (data baked).

Notes:
- Token-free sanity build (no service/data-dependent code): `docker build --target base …`.
- `tijuana_dispersion.__version__` reports `0.3.0` even though pinned at
  tag **v0.4.0** — cosmetic (the constant was never bumped upstream);
  the *code* is the v0.4.0 box+driver+puff. Don't gate on `__version__`.
- Registry choice (`registry.nrp-nautilus.io` vs GHCR) is a standing
  decision (issue "Things to figure out"); the commands assume the
  NRP registry, which the namespace can pull without extra pull-secrets.

## 2. Namespace RBAC — `dagster-nrp` ServiceAccount

The k8s_job_executor is configured with `service_account_name:
"dagster-nrp"`. Create it with just enough to manage step Jobs:

```yaml
# nrp/k8s/rbac.yaml   (apply: kubectl apply -f nrp/k8s/rbac.yaml -n ucsd-center4health)
apiVersion: v1
kind: ServiceAccount
metadata: { name: dagster-nrp }
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata: { name: dagster-nrp }
rules:
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["create", "get", "list", "watch", "delete"]
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: { name: dagster-nrp }
subjects: [{ kind: ServiceAccount, name: dagster-nrp }]
roleRef: { kind: Role, name: dagster-nrp, apiGroup: rbac.authorization.k8s.io }
```

Check: `kubectl get sa dagster-nrp -n ucsd-center4health` → exists.

## 3. Secrets

```bash
kubectl create secret generic dagster-nrp-env -n ucsd-center4health \
  --from-literal=AWS_ACCESS_KEY_ID=… \
  --from-literal=AWS_SECRET_ACCESS_KEY=… \
  --from-literal=S3_ENDPOINT_URL=https://oss.resilientservice.mooo.com \
  --from-literal=AWS_DEFAULT_REGION=us-west-2 \
  --from-literal=DAGSTER_S3_BUCKET=tj-calibration \
  --from-literal=SLACK_WEBHOOK_WATCH=… \
  --from-literal=SLACK_WEBHOOK_CRITICAL=… \
  --from-literal=NRP_NAMESPACE=ucsd-center4health
```

(Values are in `nrp/.env` locally — never commit them. `DAGSTER_S3_BUCKET`
must be set so the env-adaptive IO manager selects S3, not filesystem.)

## 4. Deploy Dagster (webserver + daemon) into the namespace

Use the official Helm chart with the in-cluster Postgres that
`nrp/.env` already points at (`dagster-postgres.ucsd-center4health.svc`).

```bash
helm repo add dagster https://dagster-io.github.io/helm
helm upgrade --install dagster dagster/dagster -n ucsd-center4health \
  -f nrp/k8s/dagster-values.yaml
```

`dagster-values.yaml` essentials (skeleton — fill image/digest/host):

```yaml
dagsterWebserver: { workspace: { enabled: true } }
dagsterDaemon: { enabled: true }                 # REQUIRED for the fan-out
runLauncher:
  type: K8sRunLauncher
  config:
    k8sRunLauncher:
      serviceAccountName: dagster-nrp
      jobNamespace: ucsd-center4health
      imagePullPolicy: IfNotPresent
      envSecrets: [{ name: dagster-nrp-env }]
postgresql:
  enabled: false                                  # use the existing one
  postgresqlHost: dagster-postgres.ucsd-center4health.svc.cluster.local
generatePostgresqlPasswordSecret: false
deployments:
  - name: nrp
    image: { repository: registry.nrp-nautilus.io/ucsd-center4health/nrp-worker, tag: "<digest>" }
    dagsterApiGrpcArgs: ["-m", "nrp.definitions"]
    port: 3030
    envSecrets: [{ name: dagster-nrp-env }]
```

Checks:
- `kubectl get pods -n ucsd-center4health` → `dagster-webserver`,
  `dagster-daemon`, and the `nrp` code-location pod all `Running`.
- `kubectl port-forward svc/dagster-webserver 3000 -n ucsd-center4health`
  → UI shows the asset graph, `sobol_chunk_results` with 100 partitions.

## 5. Smoke on-cluster (one partition as a real K8s Job)

From the UI (or `dagster job launch`), materialize
`sobol_chunk_results` partition `chunk_000`. Confirm:
- a K8s Job/pod is created (`kubectl get jobs -n ucsd-center4health`),
- it completes,
- the artifact lands at `s3://tj-calibration/dagster/runs/…/sobol_chunk_results/chunk_000`.

## 6. Full submission

```bash
# Dry-run first (prints the plan; no submission):
uv run python nrp/scripts/submit_sobol.py --dry-run --n-base-samples 8192
# Live (requires the daemon up and kube context = nautilus):
uv run python nrp/scripts/submit_sobol.py --n-base-samples 8192
```

This launches the 100-partition backfill of `sobol_chunk_results`
(fan-out to ~100 parallel Jobs, `max_concurrent: 100`) then
`sobol_aggregate`. Acceptance target: < 1 h wall-time. Monitor via the
UI or `kubectl get jobs -n ucsd-center4health -w`.

Retrieve:

```bash
uv run python nrp/scripts/fetch_sobol_results.py     # auto-detects S3 (DAGSTER_S3_BUCKET set)
# → experiments/2026-05-15_sobol_full/output/sobol_indices.csv
```

Then write up full-scale findings vs the 200-sample LHS Pearson
approximation in `experiments/2026-05-15_sobol_full/RESULTS.md`.

## 7. Standing decisions still needing a human (issue "Things to figure out")

- **Storage class / quota**: confirm the namespace can run 100
  concurrent pods (CPU/mem requests in `_WORKER_K8S_TAGS`:
  500m/1Gi req, 1/2Gi lim → ~50 CPU, ~100Gi at peak). If quota is
  lower, drop `max_concurrent` (still correct, just slower).
- **Registry**: `registry.nrp-nautilus.io` (assumed here) vs GHCR with
  an imagePullSecret.
- **Object store**: `oss.resilientservice.mooo.com` (verified) vs an
  NRP-native CephFS-backed S3 — current bucket `tj-calibration` works.

## 8. Teardown

`helm uninstall dagster -n ucsd-center4health` removes the runtime;
Jobs are owned by their runs and GC per Dagster config. Artifacts in
`s3://tj-calibration` persist (intentional — that's the result store).
