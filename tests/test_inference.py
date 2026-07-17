"""Tests du service d'inférence : logique de routage entre les modèles
(exigence minimale de l'énoncé) + comportement de l'endpoint /predict."""

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from services.inference.app import main as inf
from services.inference.app.main import NO_OFFER, app
from services.preprocessing.app.features import OFFER_LABELS

client = TestClient(app)


@pytest.fixture
def mock_preprocessing(monkeypatch):
    """Remplace l'appel HTTP au preprocessing par un vecteur fixe."""
    response = httpx.Response(
        200,
        json={"features": [0.0] * 45},
        request=httpx.Request("POST", "http://test/transform"),
    )
    monkeypatch.setattr(
        inf.preprocessing_client, "post", lambda *a, **k: response
    )


def _set_churn_score(monkeypatch, score: float) -> None:
    monkeypatch.setattr(
        inf.churn_model,
        "predict_proba",
        lambda X: np.array([[1.0 - score, score]]),
    )


def test_predict_above_threshold_calls_offer_model(
    monkeypatch, mock_preprocessing, sample_profile
):
    _set_churn_score(monkeypatch, 0.7)
    monkeypatch.setattr(
        inf.offer_model, "predict", lambda X: np.array(["remise_tarifaire"])
    )
    resp = client.post("/predict", json=sample_profile)
    assert resp.status_code == 200
    body = resp.json()
    assert body["churn_probability"] == 0.7
    assert body["recommended_offer"] == "remise_tarifaire"


def test_predict_below_threshold_skips_offer_model(
    monkeypatch, mock_preprocessing, sample_profile
):
    """En dessous du seuil, le modèle d'offre ne doit PAS être appelé."""
    _set_churn_score(monkeypatch, 0.3)

    def fail_if_called(X):
        raise AssertionError("offer_model ne devrait pas être appelé")

    monkeypatch.setattr(inf.offer_model, "predict", fail_if_called)
    resp = client.post("/predict", json=sample_profile)
    assert resp.status_code == 200
    assert resp.json()["recommended_offer"] == NO_OFFER


def test_predict_preprocessing_down_returns_503(monkeypatch, sample_profile):
    def boom(*a, **k):
        raise httpx.RequestError("connexion refusée")

    monkeypatch.setattr(inf.preprocessing_client, "post", boom)
    resp = client.post("/predict", json=sample_profile)
    assert resp.status_code == 503


def test_predict_preprocessing_error_propagated(monkeypatch, sample_profile):
    response = httpx.Response(
        422,
        json={"detail": "Champs manquants"},
        request=httpx.Request("POST", "http://test/transform"),
    )
    monkeypatch.setattr(
        inf.preprocessing_client, "post", lambda *a, **k: response
    )
    resp = client.post("/predict", json=sample_profile)
    assert resp.status_code == 422


def test_predict_integration_real_models(monkeypatch, sample_profile):
    """Intégration : vrai preprocessor + vrais modèles, HTTP mocké
    au niveau transport uniquement."""
    from services.preprocessing.app.main import app as prep_app

    prep_client = TestClient(prep_app)
    monkeypatch.setattr(
        inf.preprocessing_client,
        "post",
        lambda path, json: prep_client.post(path, json=json),
    )
    resp = client.post("/predict", json=sample_profile)
    assert resp.status_code == 200
    body = resp.json()
    assert 0.0 <= body["churn_probability"] <= 1.0
    assert body["recommended_offer"] in OFFER_LABELS + [NO_OFFER]


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "threshold" in resp.json()
