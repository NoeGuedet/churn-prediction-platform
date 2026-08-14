#!/usr/bin/env python3
"""Entraînement des trois modèles du cas 3 (churn télécom).

Produit les artefacts versionnés dans models/ :
  - preprocessor.pkl  : ColumnTransformer fitted (partagé par tous les modèles)
  - churn_model.pkl   : XGBoost binaire, score de churn entre 0 et 1
  - offer_model.pkl   : RandomForest multiclasses, recommandation d'offre
  - kmeans_model.pkl  : K-Means de segmentation (utilisé par le CronJob)

Les métriques affichées en fin d'exécution sont à reporter dans
models/README.md (fiches de validation).

Usage : .venv/bin/python scripts/train_models.py
"""

import sys
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    roc_auc_score,
    silhouette_score,
)
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from xgboost import XGBClassifier

sys.path.insert(0, str(Path(__file__).parent.parent))
from services.preprocessing.app.features import (  # noqa: E402
    CATEGORICAL_COLS,
    NUMERIC_COLS,
    OFFER_LABELS,
    prepare_frame,
)

DATA_PATH = Path(__file__).parent.parent / "data" / "churn.csv"
MODELS_DIR = Path(__file__).parent.parent / "models"
RANDOM_STATE = 42
N_SYNTHETIC = 5000
NOISE_RATE = 0.10


def assign_offer(row: pd.Series, rng: np.random.Generator) -> str:
    """Règle métier fictive attribuant une offre à un profil client.

    Sert à générer les labels synthétiques du modèle de recommandation.
    10 % de bruit pour que le problème reste apprenable mais non trivial.
    """
    if rng.random() < NOISE_RATE:
        return OFFER_LABELS[rng.integers(len(OFFER_LABELS))]
    if row["MonthlyCharges"] > 90:
        return "discount"
    if row["InternetService"] == "DSL":
        return "fiber_upgrade"
    if row["TechSupport"] == "No" and row["InternetService"] != "No":
        return "premium_support"
    if row["Contract"] == "Month-to-month" and row["tenure"] < 12:
        return "loyalty_contract"
    if row["StreamingTV"] == "Yes" or row["StreamingMovies"] == "Yes":
        return "streaming_pack"
    return "loyalty_contract"


def measure_inference_time(model, X_sample: np.ndarray, n: int = 1000) -> float:
    """Temps moyen d'inférence par ligne, en millisecondes."""
    row = X_sample[[0]]
    for _ in range(10):  # warmup
        model.predict_proba(row)
    start = time.perf_counter()
    for _ in range(n):
        model.predict_proba(row)
    return (time.perf_counter() - start) / n * 1000


def main() -> None:
    rng = np.random.default_rng(RANDOM_STATE)
    MODELS_DIR.mkdir(exist_ok=True)

    # --- Données ------------------------------------------------------
    raw = pd.read_csv(DATA_PATH)
    y = (raw["Churn"] == "Yes").astype(int).to_numpy()
    X = prepare_frame(raw)
    print(f"[DATA] {len(X)} lignes, taux de churn : {y.mean():.1%}")

    # --- Preprocessor (fit sur le train uniquement, pas de fuite) -----
    preprocessor = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_COLS),
            (
                "cat",
                OneHotEncoder(handle_unknown="ignore", sparse_output=False),
                CATEGORICAL_COLS,
            ),
        ]
    )
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )
    X_train_t = preprocessor.fit_transform(X_train)
    X_test_t = preprocessor.transform(X_test)
    print(f"[PREPROC] Vecteur transformé : {X_train_t.shape[1]} features")

    # --- Modèle 1 : churn (XGBoost) ------------------------------------
    churn_model = XGBClassifier(
        n_estimators=300,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.9,
        eval_metric="logloss",
        random_state=RANDOM_STATE,
    )
    churn_model.fit(X_train_t, y_train)
    proba = churn_model.predict_proba(X_test_t)[:, 1]
    pred = (proba >= 0.5).astype(int)
    churn_auc = roc_auc_score(y_test, proba)
    churn_acc = accuracy_score(y_test, pred)
    churn_f1 = f1_score(y_test, pred)
    churn_latency = measure_inference_time(churn_model, X_test_t)
    print(
        f"[CHURN] AUC={churn_auc:.3f}  acc={churn_acc:.3f}  "
        f"F1={churn_f1:.3f}  inférence={churn_latency:.2f} ms/ligne"
    )

    # --- Modèle 2 : recommandation d'offre (données synthétiques) ------
    synthetic_idx = rng.integers(0, len(X), size=N_SYNTHETIC)
    X_syn = X.iloc[synthetic_idx].reset_index(drop=True)
    y_syn = np.array([assign_offer(row, rng) for _, row in X_syn.iterrows()])
    X_syn_t = preprocessor.transform(X_syn)
    X_syn_train, X_syn_test, y_syn_train, y_syn_test = train_test_split(
        X_syn_t, y_syn, test_size=0.2, random_state=RANDOM_STATE
    )
    offer_model = RandomForestClassifier(
        n_estimators=100,
        max_depth=8,
        min_samples_leaf=5,
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    offer_model.fit(X_syn_train, y_syn_train)
    y_syn_pred = offer_model.predict(X_syn_test)
    offer_acc = accuracy_score(y_syn_test, y_syn_pred)
    offer_f1 = f1_score(y_syn_test, y_syn_pred, average="macro")
    offer_latency = measure_inference_time(offer_model, X_syn_t)
    print(
        f"[OFFER] acc={offer_acc:.3f}  F1-macro={offer_f1:.3f}  "
        f"inférence={offer_latency:.2f} ms/ligne"
    )

    # --- Modèle 3 : segmentation K-Means (CronJob) ----------------------
    X_all_t = preprocessor.transform(X)
    kmeans = KMeans(n_clusters=4, n_init=10, random_state=RANDOM_STATE)
    kmeans.fit(X_all_t)
    silhouette = silhouette_score(X_all_t, kmeans.labels_, sample_size=2000)
    sizes = np.bincount(kmeans.labels_)
    print(
        f"[KMEANS] silhouette={silhouette:.3f}  "
        f"clusters={dict(enumerate(sizes.tolist()))}"
    )

    # --- Sauvegarde des artefacts --------------------------------------
    artifacts = {
        "preprocessor.pkl": preprocessor,
        "churn_model.pkl": churn_model,
        "offer_model.pkl": offer_model,
        "kmeans_model.pkl": kmeans,
    }
    for name, obj in artifacts.items():
        path = MODELS_DIR / name
        joblib.dump(obj, path, compress=3)
        size_kb = path.stat().st_size / 1024
        print(f"[SAVE] {name} : {size_kb:.0f} Ko")


if __name__ == "__main__":
    main()
