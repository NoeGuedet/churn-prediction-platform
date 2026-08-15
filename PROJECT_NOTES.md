# Project notes — ML orchestration under resource constraints

> Working notes covering the project end to end: the concepts, the code, the infrastructure, the difficulties encountered and how they were solved.

## Table of contents

1. [Core concepts, in our own words](#1-core-concepts-in-our-own-words)
2. [The project: what we built](#2-the-project-what-we-built)
3. [The code, service by service](#3-the-code-service-by-service)
4. [Infrastructure: containers, CI/CD, Kubernetes](#4-infrastructure-containers-cicd-kubernetes)
5. [Difficulties encountered (and what they taught us)](#5-difficulties-encountered-and-what-they-taught-us)
6. [Load benchmarks](#6-load-benchmarks)
7. [Going further](#7-going-further)

---

## 1. Core concepts, in our own words

### 1.1 Kubernetes, the essentials

Kubernetes is a **declarative orchestrator**. You never tell it "run this program"; you write YAML files describing the **desired state** ("there must be 1 pod running image X with these resources"), and controllers continuously check that reality matches the declaration. A pod dies → it is recreated. You change the YAML → K8s performs the transition. Everything follows from this principle.

Our cluster is a **minikube**: a single-**node** cluster (a Docker VM with 4 CPUs / 6 GB on the Mac). Important point measured early in the project: the node itself consumes ~185m CPU / 622Mi **for the Kubernetes system** (kubelet, API server, etcd) — which is why a namespace quota is always lower than the node's capacity, and why allocating 100% of a node to an application is bad practice.

### 1.2 The objects we use

| Object | Role | In this project |
|---|---|---|
| **Pod** | Smallest unit: 1 running container, ephemeral IP | 1 pod per service |
| **Deployment** | "There must always be N pods of this type" + manages updates | 3 Deployments |
| **Service** | Stable DNS name in front of ephemeral pods. ClusterIP = internal, NodePort = exposed outside the cluster | 2 ClusterIP, 1 NodePort |
| **Namespace** | Logical partition of the cluster | `churn-prediction-platform` |
| **ResourceQuota** | Ceiling on the **sum** of the namespace's requests/limits | 2500m / 1.5Gi |
| **LimitRange** | Default values + min/max bounds per container | see `k8s/limitrange.yaml` |
| **CronJob** | Runs a pod on a schedule | hourly segmentation |

Why the Service is indispensable: pods have **ephemeral** IPs (a recreated pod gets another IP). Calling a pod by its IP or via `localhost` does not work. The Service provides a stable DNS name (`preprocessing-svc`) that always resolves to the live pod(s). Within the same namespace the short name is enough; the full form is `name.namespace.svc.cluster.local`.

### 1.3 The requests / limits / reality trio — the core concept

Three **different** numbers that must never be confused:

- **`requests`** = the **reservation**. The scheduler uses it to place the pod, and the ResourceQuota deducts it. Critical point: the quota counts **declared** requests, not actual consumption. A pod that declares 500m and consumes 50m still occupies 500m of the quota.
- **`limits`** = the **ceiling**. What happens when exceeded depends on the resource (see 1.4).
- **Actual consumption**, measured by `kubectl top pods` (via metrics-server). This is what calibrates the other two: requests ≈ 70–80% of the observed peak, limits ≈ 120–130%.

A ResourceQuota can count requests **and** limits (ours counts both) — a major consequence discussed in section 5. And as soon as a quota exists in a namespace, **every pod must declare requests and limits**, otherwise it is rejected at creation time: this is what the LimitRange is for (default values injected automatically).

### 1.4 CPU vs memory: two failure policies

- **CPU is compressible**: a computation can be slowed down. When `limits.cpu` is exceeded, the kernel applies **throttling**: time is sliced into 100 ms periods (cgroups), and the container gets a CPU time budget per period (e.g. `limits.cpu: 500m` → 50 ms per 100 ms window). Budget exhausted → the process waits for the next period. **Nothing crashes, nothing is logged**: latency simply rises, especially at P95/P99. This is the hardest failure mode to detect.
- **Memory is incompressible**: once allocated, it stays allocated. Exceeding `limits.memory` → **OOMKill**: the container is killed outright and restarted (`Reason: OOMKilled` in `kubectl describe pod`). If it repeats → `CrashLoopBackOff` with exponential backoff between restarts.

Connection with the Python GIL: threads do not parallelize computation, so we use **Gunicorn workers = processes**. Too few workers → requests queue up while the CPU is idle; too many workers for the allocated `limits.cpu` → all throttled at the same time. The right setting is measured, not guessed.

### 1.5 RollingUpdate and the headroom calculation

During a RollingUpdate, Kubernetes starts the new pods **before** terminating the old ones:

- `maxSurge: 1` → at most 1 pod above the desired count during the transition. The namespace temporarily hosts **2× the requests (and 2× the limits)** of the service being updated.
- `maxUnavailable: 0` → no old pod killed before the new one is Running. No downtime, but requires headroom in the quota.

The mandatory calculation before choosing the strategy:

```
headroom = quota − sum of declared values (on EACH dimension counted by the quota)
headroom ≥ requests AND limits of the largest pod to surge
```

If the headroom is insufficient: the new pod is **rejected by quota admission** (`exceeded quota`), stays Pending, and since `maxUnavailable: 0` forbids killing the old one, the update is **blocked indefinitely** — without anything crashing or logging. The alternative in that case: the `Recreate` strategy (kills everything then recreates — downtime, but no headroom required).

### 1.6 Multi-tenancy: what a quota does — and does not do

A ResourceQuota is an **admission ceiling**, not a capacity reservation. Scenario studied: 2 namespaces on 1 node, one with a quota, one without. Kubernetes **never** computes "limit of the quota-less namespace = node − the other's quota".

- At **scheduling** time: the scheduler looks at the unreserved capacity of the **whole node** (across all namespaces). A namespace without a quota can fill the node and make the other namespace's pods fail (`Pending`), even if its own quota is far from reached. First come, first served.
- At **execution** time, the **pods' requests** are what protect you: CPU is distributed proportionally to requests (cpu.shares), and under memory pressure the kubelet evicts pods without requests first (BestEffort), then those above their requests (Burstable), and Guaranteed pods last (requests = limits). Our pods are Burstable.

---

## 2. The project: what we built

### 2.1 The application

**Telecom churn prediction**: for each customer profile, predict a churn-risk score and, if the score exceeds a configurable threshold, recommend an offer among 5 categories. Business constraint: response < 200 ms. Imposed quota: **2500m CPU / 1.5Gi memory**.

Why the challenge is infrastructural: tabular models are lightweight (XGBoost ~200 KB, RandomForest ~700 KB), so the difficulty is not fitting the models but **sizing the HTTP services** — that is the real engineering problem, not the ML.

### 2.2 The flow of a request

```
Load script (JSON profiles, 10 to 150 req/min)
      │  POST /predict
      ▼  (NodePort, via minikube service or port-forward)
┌─── namespace churn-prediction-platform — quota 2500m / 1.5Gi ──┐
│                                                                │
│   ┌──────────────┐  1. raw profile  ┌────────────────┐         │
│   │  inference   │ ────────────────▶ │ preprocessing  │         │
│   │  (2 models)  │ ◀──────────────── │ /transform     │         │
│   └──────┬───────┘  2. 45-vector    └────────────────┘         │
│          │ 3. churn_model.predict_proba → score                │
│          │ 4. if score ≥ threshold → offer_model.predict       │
│          │    else → "no_offer"                                 │
│          │ 5. log (BackgroundTasks, off the critical path)      │
│          ▼                                                     │
│   ┌──────────────┐        ┌─────────────────────────┐          │
│   │  monitoring  │        │ CronJob segmentation    │          │
│   │  /metrics    │        │ (K-Means, 1×/hour)      │          │
│   └──────────────┘        └─────────────────────────┘          │
└────────────────────────────────────────────────────────────────┘
```

The load script expects exactly `{"churn_probability": float, "recommended_offer": str}`; only HTTP 200 counts as success.

### 2.3 The models

Trained outside the cluster (`scripts/train_models.py`, reproducible with a fixed seed), artifacts versioned in `models/` with validation sheets (dataset, metric, size, inference time):

| Model | Type | Metric | Size | Inference |
|---|---|---|---|---|
| churn | binary XGBoost | **AUC 0.838** | 209 KB | 0.14 ms |
| offer | RandomForest 5 classes | **accuracy 0.928** | 712 KB | ~13 ms |
| segmentation | K-Means k=4 | silhouette 0.231 | 5 KB | batch |

A reminder about AUC: the model outputs a score, not a class — a threshold is needed to decide, and accuracy depends on the threshold AND on the class imbalance (26.5% churn: an "always no" predictor already scores 73.5%). AUC measures the model's **ranking power**, independently of the threshold: the probability that a randomly picked churner has a higher score than a randomly picked loyal customer. 0.5 = random, 1.0 = perfect. The threshold itself is an operational parameter (`CHURN_THRESHOLD` environment variable).

The 5,000 synthetic offer rows are generated by fictional business rules + 10% noise (otherwise the problem would be trivially deterministic).

### 2.4 Major architecture decisions

- **2nd model inside the inference service** (no 4th pod): a Python pod costs ~200–250Mi of requests for its runtime alone (~15% of the quota) for a 700 KB model. The call is synchronous and conditional → local chaining, no network round trip within the 200 ms budget.
- **FastAPI + Gunicorn (Uvicorn workers)** for all 3 services.
- **Preprocessing is a separate service** (a requirement) but shares its logic with training via `services/preprocessing/app/features.py` — **single source of truth**: training and production transformations cannot drift apart.

---

## 3. The code, service by service

### 3.1 preprocessing (`services/preprocessing/`)

- Loads `preprocessor.pkl` (ColumnTransformer: StandardScaler on 4 numeric + OneHotEncoder on 15 categorical columns → dense vector of **45 features**) **at worker startup**.
- `POST /transform`: validates the presence of the 19 fields (422 otherwise), applies `prepare_frame` (coercion of CSV strings to float, `TotalCharges: " "` → 0.0 — a known quirk of the dataset), transforms, returns `{"features": [...]}`.
- `handle_unknown="ignore"` in the one-hot: a category never seen in production does not crash the service.
- **A single Gunicorn worker** (see section 5): 175Mi measured.

### 3.2 inference (`services/inference/`)

- Loads both models at startup. **Reused** HTTP clients (connection pooling) toward preprocessing and monitoring.
- `POST /predict`: calls preprocessing (422 errors propagated, unreachable service → 503, both are logged), computes the score, applies the **conditional routing** (offer if score ≥ threshold, otherwise `no_offer` — the offer model is then *not* called, unit-tested).
- **Monitoring off the critical path**: `BackgroundTasks` — the HTTP response is sent *before* the monitoring call, and a monitoring outage can never fail a prediction.
- 2 Gunicorn workers.

### 3.3 monitoring (`services/monitoring/`)

- `POST /log` records `{ts, latency_ms, status, churn_probability, offer}`; `GET /metrics` aggregates: volume, error rate, avg/P95/max latencies, requests in the last minute, last 10 events.
- **Bounded storage**: `deque(maxlen=10000)` + lock. The service's RAM is **constant** regardless of stress test duration — an important detail under a strict quota.

### 3.4 segmentation (CronJob, `services/segmentation/`)

Standalone script run 1×/hour: reloads `churn.csv`, applies the shared preprocessor, recomputes the K-Means, logs silhouette + cluster sizes to stdout (`kubectl logs job/...`). Only consumes resources during the run — but its requests/limits temporarily add to the quota (accounted for in the ADR).

### 3.5 Tests

17 tests, **98% coverage** (CI threshold: 80%, blocking). Covers: preprocessing functions (coercion, empty TotalCharges, column order), routing logic (offer called or not depending on the threshold, with a mock that *fails if the offer model is called by mistake*), errors (503, propagated 422), an integration test with the real artifacts, and monitoring (metrics, bounding, empty case).

---

## 4. Infrastructure: containers, CI/CD, Kubernetes

### 4.1 Docker images

- `python:3.14-slim` base for all (same version as the training venv → joblib artifact compatibility guaranteed; library versions are **pinned** in each `requirements.txt`).
- `libgomp1` installed in the inference image (OpenMP runtime required by XGBoost on Debian — the equivalent of `libomp` on macOS).
- **Optimization**: XGBoost's Linux wheel installs **401 MB of useless nvidia/CUDA libraries** in CPU-only mode → installed with `--no-deps` (numpy/scipy come from scikit-learn) → inference image **1.64 GB → 915 MB**. All images < 1 GB (no multi-stage build needed).
- Build context at the repo root (access to `models/`), `.dockerignore` to exclude venv/docs/tests.
- `docker-compose.yml`: full stack locally without Kubernetes, validated at 100% success at 300 req/min.

### 4.2 CI/CD (`.github/workflows/ci.yml`)

Three-stage GitHub Actions pipeline:

1. **test**: install, `pytest` (blocks below 80% coverage).
2. **build** (only if tests are green): **multi-arch** build (`linux/amd64` + `linux/arm64` via QEMU — the target machine may be Intel or Apple Silicon) of the 5 images in a matrix. Validation only: the images are not published to any registry.
3. **deploy** (only on `main`): the runner joins the Tailscale tailnet ephemerally (OAuth client, `tag:ci`), then redeploys the self-hosted LXC over SSH — `git pull --ff-only` + `docker compose up -d --build`. All credentials live in GitHub encrypted secrets (Tailscale OAuth client, SSH key, pinned `known_hosts`), never in plaintext.

A pipeline that deployed despite red tests would be broken by design — here both the build and the deploy explicitly depend on test success (`needs: test`).

### 4.3 Kubernetes (`k8s/`)

A single `kubectl apply -f k8s/ -n churn-prediction-platform` deploys everything: namespace, quota, limitrange, 3 Deployments+Services, CronJob.

**Final sizing, measured by `kubectl top pods`** (captures in `docs/captures/`):

| Service | requests CPU | requests mem | limits CPU | limits mem | Measured |
|---|---|---|---|---|---|
| preprocessing | 200m | 192Mi | 400m | 288Mi | 175Mi |
| inference | 450m | 448Mi | 700m | 544Mi | 250-370Mi |
| monitoring | 100m | 96Mi | 200m | 128Mi | 55-65Mi |
| **Σ permanent** | **750m** | **736Mi** | **1300m** | **960Mi** | |
| segmentation (CronJob) | 200m | 256Mi | 400m | 384Mi | ~300Mi at run |

`RollingUpdate` strategy (`maxSurge: 1`, `maxUnavailable: 0`) on all 3 services. Surge headroom verified on **both dimensions** for the worst case (inference surge):

- requests: CPU 2500−750 = 1750m ≥ 450m ✓ ; memory 1536−736 = 800Mi ≥ 448Mi ✓
- limits: CPU 2500−1300 = 1200m ≥ 700m ✓ ; memory 1536−960 = 576Mi ≥ 544Mi ✓

`readiness` + `liveness` probes on `/health` for each service. Each deployment gets its neighbors' URLs through environment variables (`PREPROCESSING_URL=http://preprocessing-svc:8001`...).

---

## 5. Difficulties encountered (and what they taught us)

### 5.1 Namespace names are lowercase (RFC 1123)

`projet-NOE` was rejected by the API (`a lowercase RFC 1123 label must consist of lower case...`) — and since namespace creation failed, **all** other resources failed in cascade (`namespace not found`). Fix: `projet-noe`. (The namespace was later renamed `churn-prediction-platform` when the project was prepared for public release.)

### 5.2 The namespace initialization race

After the fix, the namespace was created but resources applied right after were rejected by the admission controller while it became *Active*. The apply is **idempotent**: re-running the same command makes it converge. This is documented in the README so that a fresh deployment converges.

### 5.3 preprocessing above its requests

Measured at **305Mi** with 2 Gunicorn workers (each loads pandas + sklearn, ~150Mi) against 256Mi of requests → OOMKill risk under load. Rather than raising the requests, we cut down to **1 worker** (a transformation = 5–10 ms of CPU, far below 150 req/min) → **175Mi measured**. Lesson: under a strict quota, you optimize consumption before raising the budget.

### 5.4 The stuck rollout — the project's main lesson

After moving to 1 worker, the preprocessing RollingUpdate stayed frozen: `ReplicaFailure / FailedCreate` with the message `exceeded quota: ... limits.memory=384Mi, used: 1344Mi, limited: 1536Mi`. **The requests headroom was sufficient (896+256 ≤ 1536), but the limits headroom was not (1344+384 > 1536)**: our quota counts both dimensions, and the ADR's surge calculation only checked one. Worse: an inference surge also failed on CPU limits (1800+1000 > 2500). With those values, **no RollingUpdate was possible at all**.

Fix: a complete rebalancing of the budget (limits tightened to ~120–150% of the measured peak) until all **4 inequalities** (requests and limits × CPU and memory) held for the worst case. Then validated by a successful `kubectl rollout restart`. The ADR documents this correction in detail.

### 5.5 The hot budget-change deadlock

A subtlety discovered while applying the fix: the **old** pods (with the old generous limits) still occupied the quota (1344Mi), so the **new**, leaner pods could not surge either — and `maxUnavailable: 0` forbade killing the old ones first. Deadlock, resolved by recreating the deployments (acceptable in dev; on a fresh cluster — e.g., a from-scratch deployment — the problem does not arise since the final values are applied directly).

### 5.6 The 401 MB of CUDA in XGBoost

Initial inference image: 1.64 GB. Inspection → XGBoost's Linux wheel depends on 401 MB of `nvidia` (GPU) libraries, useless for CPU inference. Fix: `--no-deps`. General lesson: inspect your images (`du -sh site-packages/*`) rather than accepting their size.

---

## 6. Load benchmarks

Protocol executed (`scripts/run_challenge.sh`): 3 levels of 5 min (nominal 10 req/min, load 50, stress 150), `kubectl top pods` readings every 30 s + monitoring metrics before/after. Raw captures in `docs/captures/challenge_*.txt`.

### 6.1 Results of the 3 levels (before the fix)

| Level | Success | Avg / P95 latency (client) | Max observed CPU | Max memory | Restarts |
|---|---|---|---|---|---|
| Nominal (10/min) | 50/50 — 100% | 36 ms / 40 ms | inference 8m, preprocessing 6m | inference 252Mi | 0 |
| Load (50/min) | 250/250 — 100% | 34 ms / 39 ms | inference 12m, preprocessing 15m | inference 255Mi | 0 |
| Stress (150/min) | 744/745 — 99.9% | 33 ms / 39 ms | inference 22m, preprocessing 35m | inference 255Mi | 0 |

Server-side view (monitoring, stress level): **0 failures**, average latency **15.5 ms**, P95 20.4 ms.

### 6.2 Reading the results

- **No saturation**: latency is flat from one level to the next, CPU stays under 10% of limits everywhere (inference 22m out of 700m allowed), memory is stable → neither throttling nor OOMKill, sizing validated with headroom.
- **The single failure at stress is client-side** (0 failures in monitoring): an artifact of the port-forward tunnel, not of the system.
- **Key takeaway**: the most CPU-expensive service per request is NOT inference but **preprocessing** (35m vs 22m at stress). The cause is not the transformation itself but the **pandas/sklearn plumbing on a single row**: measured, `/transform` took ~10.8 ms of the ~15 ms of server time (~70%).

### 6.3 Fix identified and applied

**Fix: compile the preprocessor.** A `ColumnTransformer` (StandardScaler + OneHotEncoder) is a deterministic transformation: its parameters are precomputed from the fitted artifact and applied via dict lookups + numpy (`CompiledPreprocessor` in `features.py`), without rebuilding a DataFrame or running sklearn validation on each call. Secured by a **strict equivalence test** against the original transformer on 200 real profiles + edge cases (empty TotalCharges, unknown category) — no possible divergence from training.

### 6.4 Before / after (measurements)

| Metric | Before | After | Effect |
|---|---|---|---|
| `/transform` average | 10.8 ms | 5.2 ms | **−52%** |
| `/transform` P95 | 29.5 ms | 6.4 ms | **−78%** |
| Stress 150 req/min — success | 99.9% (744/745) | **100% (745/745)** | |
| Stress — avg / P95 latency (client) | 33 / 39 ms | **23 / 29 ms** | **−30% / −26%** |
| Stress — avg server latency (monitoring*) | 15.5 ms | ≈ 6 ms | **−60%** |
| Stress — max preprocessing CPU | 35m | **9m** | **−74%** |

\* post-fix server latency estimated from the difference of the monitoring's cumulative averages over the test window.

The remaining `/transform` overhead after the fix (~5 ms) is HTTP/uvicorn overhead through the port-forward, not the transformation itself (~0.2 ms measured). Noteworthy fact: the segmentation CronJob ran **during** the post-fix stress test (hourly schedule) — 0 failures despite its 384Mi of limits temporarily added to the quota.

---

## 7. Going further

### 7.1 Message queue + batch inference

**The observation**: today each HTTP request triggers an individual synchronous inference (1 row at a time). Under load spikes, the fixed per-request cost (HTTP call to preprocessing, Python overheads, row-by-row `predict_proba` calls) is not amortized, and workers must be sized for the peak.

**The target architecture**: the HTTP API becomes a simple **producer** that pushes profiles into a **message queue** and responds immediately with an identifier (asynchronous pattern), or waits for the result with a short timeout. A pool of **consumer workers** pulls messages **in batches** (batch of N) and calls `predict_proba` on an **N-row matrix** in one go — vectorized inference is far more efficient than N individual calls (fixed costs amortized, better CPU utilization).

**The trade-off, well understood**: batching **reduces latency under load** (the CPU bottleneck is smoothed, throughput rises, P95/P99 come down) **at the price of a little latency at idle**: under low traffic, a request may wait for the batch window to fill (or expire, typically 20–100 ms) before being processed. Under load, the window fills instantly, so no extra waiting. For our specific case (XGBoost at ~0.14 ms/row), the gain would be modest; for a heavy model (CNN, GPU), this is the standard architecture.

### 7.2 Why SQS rather than Redis (in our context)

Both fill the queue role, but not with the same model:

- **SQS (AWS)** is **managed**: no broker to install, patch, monitor, or size — and above all **no footprint in our 1.5 Gi quota**. *At-least-once* delivery semantics with *visibility timeout* (an unacknowledged message reappears → no loss if a worker dies mid-processing), native **DLQ** for failed messages, pay-per-use pricing that drops to zero when there is no traffic. Queue depth also becomes an **autoscaling metric** (KEDA can scale workers from 0 to N based on queue depth).
- **Redis** (self-hosted in the cluster, or ElastiCache) is excellent on latency (sub-millisecond) and its Streams offer similar semantics, but: it is **one more stateful service to operate** in the cluster (RAM, persistence, failover), its RAM comes out of our quota, and in simple pub/sub mode delivery is *fire-and-forget* (an absent consumer loses messages — you need Streams + consumer groups for durability, hence more complexity).

For a project whose core theme is operating under a tight resource budget, externalizing queue state to a managed service is consistent: we spend our memory budget on what produces value (inference), not on plumbing. In real AWS production, we would add KEDA (autoscaling on queue depth) and an API Gateway in front.

### 7.3 Other leads

- **HPA** (Horizontal Pod Autoscaler): scale the number of inference replicas on measured CPU instead of static sizing — the natural next step for this project (caveat: the quota bounds the number of pods, the headroom calculation remains necessary).
- **Prometheus + Grafana** instead of the custom monitoring: throttling counters (`container_cpu_cfs_throttled_periods_total`) directly visible, alerts, dashboards.
- **VPA** (Vertical Pod Autoscaler) in recommendation mode: suggests requests/limits from history — industrializes what we did by hand with `kubectl top`.

---

*Working document maintained throughout the project.*
