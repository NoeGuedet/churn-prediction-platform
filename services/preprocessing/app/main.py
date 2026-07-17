"""Service de preprocessing — cas 3 (churn télécom).

Reçoit un profil client brut (JSON, champs potentiellement en string),
applique le preprocessor entraîné (scaling + one-hot) et renvoie le
vecteur de features pour le service d'inférence.
"""

import os
from pathlib import Path

import joblib
from fastapi import FastAPI, HTTPException

from .features import ALL_FEATURES, CompiledPreprocessor, prepare_frame

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "models"))

app = FastAPI(title="preprocessing", version="1.0.0")

# Chargé une fois au démarrage du worker (pic mémoire au chargement,
# consommation stable ensuite — cf. ADR), puis compilé : la transformation
# est appliquée par lookups + numpy (~1 ms) plutôt que par la plomberie
# pandas/sklearn (~10 ms), à résultat strictement identique.
compiled = CompiledPreprocessor(joblib.load(MODELS_DIR / "preprocessor.pkl"))


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/transform")
def transform(profile: dict) -> dict:
    """Transforme un profil brut en vecteur de features (45 floats)."""
    missing = [c for c in ALL_FEATURES if c not in profile]
    if missing:
        raise HTTPException(
            status_code=422, detail=f"Champs manquants : {missing}"
        )
    try:
        vector = compiled.transform_row(profile)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail=f"Profil invalide : {exc}"
        ) from exc
    return {"features": vector.tolist()}
