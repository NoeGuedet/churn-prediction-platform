"""Monitoring service — telecom churn.

Records the events sent by the inference service (requests,
predictions, latencies, statuses) and exposes aggregated metrics on
GET /metrics: volume, latency, error rate.

Bounded in-memory storage (fixed-size deque): the service's RAM
consumption stays constant regardless of the stress test duration —
an important point under a strict quota.
"""

import threading
import time
from collections import deque

from fastapi import FastAPI

MAX_EVENTS = 10_000

app = FastAPI(title="monitoring", version="1.0.0")

lock = threading.Lock()
events: deque = deque(maxlen=MAX_EVENTS)
started_at = time.time()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/log")
def log(event: dict) -> dict:
    with lock:
        events.append(event)
    return {"recorded": True}


@app.get("/metrics")
def metrics() -> dict:
    with lock:
        snapshot = list(events)
    total = len(snapshot)
    successes = sum(1 for e in snapshot if e.get("status") == 200)
    latencies = sorted(
        e["latency_ms"] for e in snapshot if e.get("latency_ms") is not None
    )
    now = time.time()
    last_minute = sum(1 for e in snapshot if now - e.get("ts", 0) <= 60)

    def pct(p: float) -> float | None:
        if not latencies:
            return None
        return round(latencies[min(len(latencies) - 1, int(p * len(latencies)))], 2)

    return {
        "uptime_s": round(now - started_at, 1),
        "total_requests": total,
        "success_200": successes,
        "failures": total - successes,
        "error_rate_pct": round((total - successes) / total * 100, 2) if total else 0.0,
        "requests_last_minute": last_minute,
        "latency_avg_ms": (
            round(sum(latencies) / len(latencies), 2) if latencies else None
        ),
        "latency_p95_ms": pct(0.95),
        "latency_max_ms": latencies[-1] if latencies else None,
        "recent_events": snapshot[-10:],
    }
