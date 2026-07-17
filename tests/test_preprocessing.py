"""Tests du service de preprocessing : fonctions de transformation
(exigence minimale de l'énoncé) + endpoint /transform."""

import pandas as pd
from fastapi.testclient import TestClient

from services.preprocessing.app.features import (
    ALL_FEATURES,
    CATEGORICAL_COLS,
    NUMERIC_COLS,
    prepare_frame,
)
from services.preprocessing.app.main import app

client = TestClient(app)


def test_prepare_frame_coerces_numeric_strings(sample_profile):
    frame = prepare_frame(pd.DataFrame([sample_profile]))
    for col in NUMERIC_COLS:
        assert pd.api.types.is_float_dtype(frame[col])


def test_prepare_frame_handles_empty_totalcharges(sample_profile):
    """Cas connu du dataset Telco : TotalCharges vide (' ') pour les
    clients à tenure 0 — doit devenir 0.0, pas lever d'erreur."""
    profile = {**sample_profile, "TotalCharges": " "}
    frame = prepare_frame(pd.DataFrame([profile]))
    assert frame["TotalCharges"].iloc[0] == 0.0


def test_prepare_frame_column_order_and_selection(sample_profile):
    profile = {**sample_profile, "ChampInconnu": "x"}
    frame = prepare_frame(pd.DataFrame([profile]))
    assert list(frame.columns) == ALL_FEATURES


def test_prepare_frame_categoricals_as_str(sample_profile):
    frame = prepare_frame(pd.DataFrame([sample_profile]))
    for col in CATEGORICAL_COLS:
        assert pd.api.types.is_object_dtype(frame[col]) or pd.api.types.is_string_dtype(frame[col])


def test_transform_ok(sample_profile):
    resp = client.post("/transform", json=sample_profile)
    assert resp.status_code == 200
    features = resp.json()["features"]
    assert len(features) == 45
    assert all(isinstance(v, float) for v in features)


def test_transform_missing_field_returns_422(sample_profile):
    profile = {k: v for k, v in sample_profile.items() if k != "tenure"}
    resp = client.post("/transform", json=profile)
    assert resp.status_code == 422
    assert "tenure" in resp.json()["detail"]


def test_health():
    assert client.get("/health").status_code == 200
