"""Monitoring service tests: event recording, aggregated metrics
and bounded in-memory storage."""

import time

from fastapi.testclient import TestClient

from services.monitoring.app.main import MAX_EVENTS, app, events

client = TestClient(app)


def _event(status: int, latency_ms: float) -> dict:
    return {
        "ts": time.time(),
        "latency_ms": latency_ms,
        "status": status,
        "churn_probability": 0.42,
        "offer": "remise_tarifaire",
    }


def test_log_then_metrics():
    events.clear()
    assert client.post("/log", json=_event(200, 10.0)).status_code == 200
    client.post("/log", json=_event(200, 30.0))
    client.post("/log", json=_event(503, 5.0))

    m = client.get("/metrics").json()
    assert m["total_requests"] == 3
    assert m["success_200"] == 2
    assert m["failures"] == 1
    assert m["error_rate_pct"] == 33.33
    assert m["latency_avg_ms"] == 15.0
    assert m["latency_max_ms"] == 30.0


def test_storage_is_bounded():
    """Storage is bounded: the service's RAM stays constant even
    after millions of logged requests."""
    assert events.maxlen == MAX_EVENTS


def test_metrics_empty():
    events.clear()
    m = client.get("/metrics").json()
    assert m["total_requests"] == 0
    assert m["latency_avg_ms"] is None


def test_health():
    assert client.get("/health").status_code == 200
