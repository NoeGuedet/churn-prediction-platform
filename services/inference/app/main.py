"""Inference service — case 3 (telecom churn).

Receives a raw customer profile on POST /predict, delegates the
transformation to the preprocessing service, computes the churn score
(XGBoost) and, if the score exceeds the configured threshold, the offer
recommendation (RandomForest). Each request is then logged to the
monitoring service, off the critical path (BackgroundTasks).
"""

import os
import time
from pathlib import Path

import httpx
import joblib
import numpy as np
from fastapi import BackgroundTasks, FastAPI, HTTPException

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "models"))
PREPROCESSING_URL = os.environ.get("PREPROCESSING_URL", "http://localhost:8001")
MONITORING_URL = os.environ.get("MONITORING_URL", "http://localhost:8003")
CHURN_THRESHOLD = float(os.environ.get("CHURN_THRESHOLD", "0.5"))

NO_OFFER = "no_offer"

app = FastAPI(title="inference", version="1.0.0")

# Artifacts loaded once at worker startup.
churn_model = joblib.load(MODELS_DIR / "churn_model.pkl")
offer_model = joblib.load(MODELS_DIR / "offer_model.pkl")

# Reused HTTP clients (connection pool) instead of being recreated
# on every request.
preprocessing_client = httpx.Client(base_url=PREPROCESSING_URL, timeout=5.0)
monitoring_client = httpx.Client(base_url=MONITORING_URL, timeout=2.0)


def log_to_monitoring(event: dict) -> None:
    """Logs an event; never interrupts the business path."""
    try:
        monitoring_client.post("/log", json=event)
    except httpx.HTTPError:
        pass  # Monitoring must never fail a prediction.


def build_event(latency_ms: float, status: int, result: dict | None) -> dict:
    return {
        "ts": time.time(),
        "latency_ms": round(latency_ms, 2),
        "status": status,
        "churn_probability": (
            result.get("churn_probability") if result else None
        ),
        "offer": result.get("recommended_offer") if result else None,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "threshold": CHURN_THRESHOLD}


@app.post("/predict")
def predict(profile: dict, background_tasks: BackgroundTasks) -> dict:
    t0 = time.perf_counter()

    # 1. Preprocessing (dedicated service).
    try:
        resp = preprocessing_client.post("/transform", json=profile)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # The preprocessing service returned an error (e.g. 422 invalid
        # profile): propagate the status for an accurate error metric.
        latency = (time.perf_counter() - t0) * 1000
        status = exc.response.status_code
        background_tasks.add_task(log_to_monitoring, build_event(latency, status, None))
        raise HTTPException(status_code=status, detail=exc.response.text) from exc
    except httpx.RequestError as exc:
        # Preprocessing unreachable.
        latency = (time.perf_counter() - t0) * 1000
        background_tasks.add_task(log_to_monitoring, build_event(latency, 503, None))
        raise HTTPException(
            status_code=503, detail=f"preprocessing unavailable: {exc}"
        ) from exc
    features = np.array([resp.json()["features"]])

    # 2. Churn score, then conditional routing to the offer model.
    churn_probability = float(churn_model.predict_proba(features)[0, 1])
    if churn_probability >= CHURN_THRESHOLD:
        offer = str(offer_model.predict(features)[0])
    else:
        offer = NO_OFFER

    result = {
        "churn_probability": round(churn_probability, 4),
        "recommended_offer": offer,
    }

    # 3. Logging off the critical path: the response is returned
    # before the monitoring call is executed.
    latency = (time.perf_counter() - t0) * 1000
    background_tasks.add_task(
        log_to_monitoring, build_event(latency, 200, result)
    )
    return result
