# Extreme stress test — beyond the required load levels

Churn prediction platform, namespace `churn-prediction-platform`. Protocol: `scripts/load_test.py --level extreme --rate N --duration 300`, increasing 5-minute steps, quota and LimitRange **unchanged** from the baseline load tests. Raw captures: `docs/captures/extreme.txt` (steps 200→1500) and `docs/captures/extreme2.txt` (steps 2000→3000).

## 1. Raw results

| Step (req/min) | Sent | Succeeded (HTTP 200) | Rate | Avg latency | P95 latency | Pod restarts |
|---|---|---|---|---|---|---|
| 200 | 990 | 990 | 100% | 24 ms | 30 ms | 0 |
| 300 | 1477 | 1477 | 100% | 23 ms | 29 ms | 0 |
| 500 | 2435 | 2435 | 100% | 22 ms | 29 ms | 0 |
| 700 | 3375 | 3375 | 100% | 19 ms | 27 ms | 0 |
| 900 | 4285 | 4285 | 100% | 16 ms | 22 ms | 0 |
| 1200 | 5605 | 5605 | 100% | 14 ms | 18 ms | 0 |
| 1500 | 6878 | 6878 | 100% | 13 ms | 16 ms | 0 |
| 2000 | 8903 | 8903 | 100% | 12 ms | 15 ms | 0 |
| 2500 | 10834 | 10834 | 100% | 11 ms | 14 ms | 0 |
| **3000** | **12638** | **12638** | **100%** | **10 ms** | **13 ms** | **0** |

**Maximum sustained throughput: 12,638 HTTP 200 requests in 5 minutes (3000 req/min configured, ~42 req/s effective), with 0 restarts and 0 OOMKills.** No step dropped below 80%: the system's breaking point was not reached within the limits of the protocol.

## 2. Identifying the breaking point (not reached — analysis of the measured ceiling)

The system did not break: the analysis therefore covers what actually limited the test, and a measurement-based projection of what would break first.

**What limited the test: the client side, not the cluster.** Quantified evidence:

- At the 3000 step, **12,638 effective requests out of 15,000 configured (84%)**: the generator (pool of 40 threads, one new TCP connection per request) can no longer emit at the requested rate, while the pods are far from their limits.
- **Latency decreases** as throughput rises (24 ms → 10 ms): at low throughput, each request pays the cost of establishing a connection through the `kubectl port-forward` tunnel (websocket proxy via the API server) and the Docker Desktop network layer on macOS; at high throughput that cost is amortized. On the server side (monitoring), latency is ~6 ms versus 10–24 ms on the client side: the gap is transport, not the application.
- Resources at the maximum step: inference **118m CPU out of a 700m** limit (17%), memory **258Mi out of 544Mi**, preprocessing 28m/400m, monitoring 25m/200m. No saturation, no restarts.

These limits are **specific to the test bench** (macOS + Docker Desktop + port-forward + 40 threads): in a proper industrialization (direct NodePort/Ingress access without a tunnel, native Linux networking, keep-alive connections), they disappear.

**Projection: what would break first.** Extrapolating the measured slope (~5m of inference CPU per 100 effective req/min at the higher steps), inference would hit its `limits.cpu` of 700m at around **14,000 req/min** — roughly 5× beyond the generator's ceiling. The first failure mode would be **CPU throttling** of inference (silent P95 degradation, no crash — CPU is compressible), not an OOMKill: memory is flat across the whole range (bounded monitoring storage, no persistent per-request allocation).

## 3. Recovery

No degradation to recover from: 0 restarts, 0 OOMKills, 0 CrashLoopBackOff across the 10 steps. Stable state confirmed immediately after the last step (the "stable in under 2 minutes" design target comfortably met):

### Recovery capture — kubectl get pods (system stable, 15:14:05)

```
NAME                             READY   STATUS      RESTARTS   AGE
inference-dcf79545d-bdz2p        1/1     Running     0          103m
monitoring-6dcbc9797-s4p72       1/1     Running     0          103m
preprocessing-7c7dc7549d-2rdzb   1/1     Running     0          54m
segmentation-29738227-h6vjx      0/1     Completed   0          7m5s
```

## 4. Improvement proposal (if the quota were doubled, 1.5Gi → 3Gi)

Reasoning based on measurements, not intuition. The **only metric that grows with load** is inference CPU (8m at idle → 118m at 3000 req/min); memory is flat everywhere, and preprocessing and monitoring stay under 30m. Doubling the quota should therefore serve inference, not memory:

- **2 inference replicas** (requests 450m/448Mi each): load spread across two pods, P95 smoothing at high throughput, and tolerance to a pod restart during a peak. Cost: +450m/+448Mi of requests — painless within 3Gi, and the surge remains computable (Σ requests 1200m/1184Mi, Σ limits 2240m/1504Mi, sufficient headroom for `maxSurge: 1`).
- **inference `limits.cpu` raised to 1000m** per replica: pushes the projected throttling point from ~14,000 to ~28,000 effective req/min in total.
- Nothing for preprocessing (28m at peak against 400m) or monitoring (bounded by construction): adding resources there would be a waste of quota, contrary to the project's resource discipline.
