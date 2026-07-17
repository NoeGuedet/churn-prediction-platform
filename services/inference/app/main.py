"""Service d'inférence — cas 3 (churn télécom).

Reçoit un profil client brut sur POST /predict, délègue la
transformation au service de preprocessing, calcule le score de churn
(XGBoost) et, si le score dépasse le seuil configuré, la recommandation
d'offre (RandomForest). Chaque requête est ensuite journalisée auprès
du service de monitoring, hors du chemin critique (BackgroundTasks).
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

NO_OFFER = "aucune_offre"

app = FastAPI(title="inference", version="1.0.0")

# Artefacts chargés une fois au démarrage du worker.
churn_model = joblib.load(MODELS_DIR / "churn_model.pkl")
offer_model = joblib.load(MODELS_DIR / "offer_model.pkl")

# Clients HTTP réutilisés (pool de connexions) plutôt que recréés
# à chaque requête.
preprocessing_client = httpx.Client(base_url=PREPROCESSING_URL, timeout=5.0)
monitoring_client = httpx.Client(base_url=MONITORING_URL, timeout=2.0)


def log_to_monitoring(event: dict) -> None:
    """Journalise un événement ; n'interrompt jamais le chemin métier."""
    try:
        monitoring_client.post("/log", json=event)
    except httpx.HTTPError:
        pass  # Le monitoring ne doit jamais faire échouer une prédiction.


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

    # 1. Preprocessing (service dédié).
    try:
        resp = preprocessing_client.post("/transform", json=profile)
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # Le preprocessing a répondu une erreur (ex. 422 profil invalide) :
        # on propage le statut pour une métrique d'erreur fidèle.
        latency = (time.perf_counter() - t0) * 1000
        status = exc.response.status_code
        background_tasks.add_task(log_to_monitoring, build_event(latency, status, None))
        raise HTTPException(status_code=status, detail=exc.response.text) from exc
    except httpx.RequestError as exc:
        # Preprocessing injoignable.
        latency = (time.perf_counter() - t0) * 1000
        background_tasks.add_task(log_to_monitoring, build_event(latency, 503, None))
        raise HTTPException(
            status_code=503, detail=f"preprocessing indisponible : {exc}"
        ) from exc
    features = np.array([resp.json()["features"]])

    # 2. Score de churn, puis routage conditionnel vers le modèle d'offre.
    churn_probability = float(churn_model.predict_proba(features)[0, 1])
    if churn_probability >= CHURN_THRESHOLD:
        offer = str(offer_model.predict(features)[0])
    else:
        offer = NO_OFFER

    result = {
        "churn_probability": round(churn_probability, 4),
        "recommended_offer": offer,
    }

    # 3. Journalisation hors du chemin critique : la réponse est renvoyée
    # avant que l'appel au monitoring ne soit exécuté.
    latency = (time.perf_counter() - t0) * 1000
    background_tasks.add_task(
        log_to_monitoring, build_event(latency, 200, result)
    )
    return result
