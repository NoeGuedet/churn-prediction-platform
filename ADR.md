# Architecture Decision Record

Telecom churn prediction and offer recommendation. Namespace `churn-prediction-platform` (Kubernetes namespace names must be lowercase, RFC 1123). Imposed quota: **2500m CPU / 1.5Gi memory**, non-negotiable.

## 1. Context and compatibility with the quota

The platform predicts churn and recommends offers for a telecom operator, with a business constraint of responding in under 200 ms. This is compatible with the imposed quota for a structural reason: both models to be served are lightweight tabular models (an ~20 MB XGBoost for the churn score, a few-MB multiclass classifier for offer recommendation), so memory is not consumed by model weights but by the Python runtimes of the services. The challenge is not fitting the models, but correctly sizing the HTTP workers of the services against inference latency at 150 req/min, without wasting requests inside a memory quota of only 1.5 Gi.

The sizing reasoning follows the nature of each service. Preprocessing loads no model: it applies tabular transformations (categorical encoding, scaling) whose cost is mostly CPU in short bursts, with modest, stable memory that we estimate at 200–250 Mi. Inference loads its two models at startup — the memory peak happens when loading the weights, not under load — and then consumes the Python/scikit-learn/XGBoost runtime, roughly 400–500 Mi in total. Monitoring only counts and stores metrics in memory; its baseline consumption is low (~130 Mi) and grows only slowly with the volume of recorded requests. The segmentation CronJob only consumes resources while running (a few minutes per hour), but its requests temporarily add to the quota during that window.

These estimates were then checked against real measurements (`kubectl top pods`), and the final sizing is as follows:

| Service | requests CPU | requests memory | limits CPU | limits memory | Measured (`kubectl top`) |
|---|---|---|---|---|---|
| preprocessing (1 worker) | 200m | 192Mi | 400m | 288Mi | 175Mi |
| inference | 450m | 448Mi | 700m | 544Mi | 250-370Mi |
| monitoring | 100m | 96Mi | 200m | 128Mi | 55-65Mi |
| segmentation (CronJob) | 200m | 256Mi | 400m | 384Mi | ~300Mi during the run |

The sum of permanent requests is **750m CPU / 736Mi** (30% and 48% of the quota), the sum of limits is **1300m / 960Mi**. Two calibrations derived from measurement are worth recording. First, preprocessing measured at 305Mi with 2 Gunicorn workers (each loads pandas + scikit-learn, ~150Mi) exceeded its 256Mi requests: since a transformation costs only 5–10 ms of CPU, we moved to **a single worker** — 175Mi measured — rather than raising the requests, in keeping with quota discipline. Second, the measured values allowed us to tighten the limits to ~120–150% of the observed peak, which proved essential for section 5.

## 2. Dataset and license

The chosen dataset is Telco Customer Churn, published by IBM as a sample dataset: 7,043 customers described by 21 variables (contract data, subscribed services, billing), in a CSV of about 950 KB. It is freely redistributed — it can be found on IBM's GitHub, on Kaggle, and in the UCI ML Repository — which guarantees its reusability for this project. The file is versioned at `data/churn.csv` and is used both to train the churn model and by the load script. For the offer recommendation model, we generate 5,000 synthetic rows derived from this same dataset, with 5 fictional offer categories, per the original project requirements.

## 3. Inter-service communication and placement of the second model

The three services communicate over the cluster's internal network through ClusterIP Service objects, which provide a stable DNS name independent of the pods' ephemeral IPs. The flow of a request is as follows: the load script calls `POST /predict` on the inference service, exposed outside the cluster via `minikube service`; inference forwards the raw customer profile to the preprocessing service (`http://preprocessing-svc:8001/transform`), which applies the transformations and returns the feature vector; inference computes the churn score, calls the recommendation model if the score exceeds the configured threshold, then notifies the monitoring service (`http://monitoring-svc:8003/log`), which records the request, the prediction, and the latency. Monitoring exposes its metrics (volume, latency, error rate) on a dedicated endpoint, reachable during tests via `kubectl port-forward`.

The second model lives inside the main inference service, not in a dedicated fourth service. The justification is first a matter of quota: an extra Python pod would cost 200–250 Mi of requests for its runtime alone — about 15% of the memory quota — to host a model of a few megabytes, a waste the 1.5 Gi quota does not allow. The justification is also functional: the call to the offer model is synchronous and conditional (only when the churn score exceeds the threshold), so chaining it locally avoids a network round trip within a 200 ms latency budget. The accepted trade-off is that both models are deployed together: updating one redeploys the other, which is acceptable here since both artifacts evolve rarely and the RollingUpdate (section 5) makes that redeployment interruption-free.

## 4. CI/CD tool

We chose GitHub Actions, for two concrete criteria. The first is native integration with the repository: the code is already hosted on GitHub, the pipeline triggers on push and pull request with no third-party infrastructure, and the workflow file (`.github/workflows/ci.yml`) is versioned with the code, which directly serves the project's reproducibility requirements. The second criterion is secrets management and the ecosystem: deployment credentials (Tailscale OAuth client, SSH key) are stored in GitHub's encrypted secrets and never in plaintext in the repo (an explicit project requirement), and the official actions (`actions/setup-python` with pip caching, `docker/build-push-action`) allow a short, readable, fast pipeline. The pipeline runs the tests with a blocking 80% coverage threshold, then validates the multi-arch builds only if the tests pass.

For deployment, the images are deliberately **not published to any registry**: on every push to `main`, a runner joins the Tailscale network ephemerally and redeploys the self-hosted LXC over SSH (`git pull` + `docker compose up -d --build`). No SSH port is exposed to the internet, and the deploy job can be gated by a manual approval through a GitHub Environment.

## 5. Deployment strategy

We use `RollingUpdate` with `maxSurge: 1` and `maxUnavailable: 0` for the inference service, to guarantee zero service interruption during updates — including during live demonstrations. The critical point, learned the hard way, is that **the surge headroom must be checked on both quota dimensions, requests AND limits**: our quota accounts for both, and an early version of the sizing (more generous limits, Σ limits.memory of 1344Mi) produced a stuck rollout — `exceeded quota: ... limits.memory=384Mi, used: 1344Mi, limited: 1536Mi` — even though the requests headroom was sufficient. The new pod could not be created, and since `maxUnavailable: 0` forbids killing the old one first, the update stayed frozen without anything crashing.

The corrected calculation, for the worst case (surge of inference, the largest pod), is as follows. Headroom = quota − sum of permanent values:

- **requests**: CPU (2500 − 750) = 1750m ≥ 450m ✓ ; memory (1536 − 736) = 800Mi ≥ 448Mi ✓
- **limits**: CPU (2500 − 1300) = 1200m ≥ 700m ✓ ; memory (1536 − 960) = 576Mi ≥ 544Mi ✓

All four inequalities hold, so the new pod can start before the old one stops without violating the quota. This property was validated experimentally by a `kubectl rollout restart deployment/inference` executed successfully immediately after the fix. The surges of preprocessing (200m / 192Mi requests) and monitoring (100m / 96Mi) hold a fortiori.

One point of vigilance remains: if an inference rollout coincides with a run of the segmentation CronJob (limits 400m / 384Mi), the sum of limits.memory reaches 960 + 384 = 1344Mi and the remaining headroom (192Mi) is no longer enough for the 544Mi surge. This risk is handled operationally rather than by over-provisioning: the CronJob is scheduled hourly for a run of a few minutes, and updates are rare manual operations we perform outside those windows; the residual risk is a temporarily pending rollout, with no service interruption since `maxUnavailable: 0` keeps the old pod active. A `LimitRange` completes the setup by imposing default values (defaultRequest 100m / 128Mi, default 250m / 256Mi) and bounds (min 50m / 64Mi, max 1000m / 768Mi) consistent with the sizing table, so that no container can declare resources outside the planned envelope.
