"""Preprocessing service — telecom churn.

Receives a raw customer profile (JSON, fields potentially as strings),
applies the trained preprocessor (scaling + one-hot) and returns the
feature vector for the inference service.
"""

import os
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException

from .features import ALL_FEATURES, CompiledPreprocessor, prepare_frame

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "models"))

app = FastAPI(title="preprocessing", version="1.0.0")

# Loaded once at worker startup (memory peak at load time, stable
# consumption afterwards — see ADR), then compiled: the transformation
# is applied via lookups + numpy (~1 ms) instead of the pandas/sklearn
# plumbing (~10 ms), with a strictly identical result.
compiled = CompiledPreprocessor(joblib.load(MODELS_DIR / "preprocessor.pkl"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/transform")
def transform(profile: dict) -> dict:
    """Transforms a raw profile into a feature vector (45 floats)."""
    missing = [c for c in ALL_FEATURES if c not in profile]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"Missing fields: {missing}"
        )
    try:
        vector = compiled.transform_row(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Invalid profile: {exc}"
        ) from exc
    return {"features": vector.tolist()}
