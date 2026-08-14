"""Preprocessing service tests: transformation functions
(minimum requirement of the assignment) + /transform endpoint."""

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from services.preprocessing.app.features import (
    ALL_FEATURES,
    CATEGORICAL_COLS,
    NUMERIC_COLS,
    prepare_frame,
)
from services.preprocessing.app.main import app, compiled

client = TestClient(app)


def test_prepare_frame_coerces_numeric_strings(sample_profile):
    frame = prepare_frame(pd.DataFrame([sample_profile]))
    for col in NUMERIC_COLS:
        assert pd.api.types.is_float_dtype(frame[col])


def test_prepare_frame_handles_empty_totalcharges(sample_profile):
    """Known Telco dataset edge case: empty TotalCharges (' ') for
    customers with tenure 0 — must become 0.0, not raise an error."""
    profile = {**sample_profile, "TotalCharges": " "}
    frame = prepare_frame(pd.DataFrame([profile]))
    assert frame["TotalCharges"].iloc[0] == 0.0


def test_prepare_frame_column_order_and_selection(sample_profile):
    profile = {**sample_profile, "UnknownField": "x"}
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


def test_compiled_matches_sklearn_transformer():
    """Strict equivalence between the CompiledPreprocessor and the
    original ColumnTransformer, on 200 real profiles + edge cases."""
    import csv
    import joblib

    original = joblib.load("models/preprocessor.pkl")
    with open("data/churn.csv") as f:
        rows = [row for _, row in zip(range(200), csv.DictReader(f))]
    for row in rows:
        row.pop("Churn", None)
        row.pop("customerID", None)
    # Edge cases: empty TotalCharges + a category never seen during training.
    rows[0] = {**rows[0], "TotalCharges": " "}
    rows[1] = {**rows[1], "Contract": "UnknownCategory"}
    for row in rows:
        expected = original.transform(prepare_frame(pd.DataFrame([row])))[0]
        assert np.allclose(compiled.transform_row(row), expected)


def test_transform_missing_field_returns_422(sample_profile):
    profile = {k: v for k, v in sample_profile.items() if k != "tenure"}
    resp = client.post("/transform", json=profile)
    assert resp.status_code == 422
    assert "tenure" in resp.json()["detail"]


def test_health():
    assert client.get("/health").status_code == 200
