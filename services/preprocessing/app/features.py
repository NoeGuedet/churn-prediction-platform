"""Définition des features Telco Churn — source de vérité unique.

Ce module est importé à la fois par le script d'entraînement
(scripts/train_models.py) et par le service de preprocessing, afin de
garantir que les transformations appliquées à l'entraînement et en
production sont strictement identiques.
"""

import pandas as pd

# Colonnes numériques (le script de charge envoie des strings issues du CSV,
# d'où la coercion systématique dans prepare_frame).
NUMERIC_COLS = ["SeniorCitizen", "tenure", "MonthlyCharges", "TotalCharges"]

CATEGORICAL_COLS = [
    "gender",
    "Partner",
    "Dependents",
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
]

# Ordre des features tel qu'attendu en entrée du preprocessor.
ALL_FEATURES = NUMERIC_COLS + CATEGORICAL_COLS

# Les 5 catégories d'offres fictives (cas 3).
OFFER_LABELS = [
    "remise_tarifaire",
    "pack_support_premium",
    "upgrade_fibre",
    "engagement_fidelite",
    "pack_streaming",
]

# Offre renvoyée lorsque le score de churn ne dépasse pas le seuil.
NO_OFFER = "aucune_offre"


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise un DataFrame brut (CSV ou JSON du script de charge).

    - Coerce les colonnes numériques en float (les valeurs arrivent en
      string depuis le CSV / le JSON du script de charge ; les champs
      vides comme TotalCharges deviennent NaN puis 0).
    - Force les colonnes catégorielles en str.
    - Retourne uniquement les colonnes features, dans l'ordre attendu.
    """
    df = df.copy()
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    for col in CATEGORICAL_COLS:
        df[col] = df[col].astype(str)
    return df[ALL_FEATURES]
