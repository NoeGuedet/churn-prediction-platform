"""Définition des features Telco Churn — source de vérité unique.

Ce module est importé à la fois par le script d'entraînement
(scripts/train_models.py) et par le service de preprocessing, afin de
garantir que les transformations appliquées à l'entraînement et en
production sont strictement identiques.
"""

import numpy as np
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
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
    for col in CATEGORICAL_COLS:
        df[col] = df[col].astype(str)
    return df[ALL_FEATURES]


def _to_float(value) -> float:
    """Reproduit to_numeric(errors='coerce').fillna(0) pour un scalaire."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class CompiledPreprocessor:
    """Version « compilée » du ColumnTransformer (StandardScaler + OneHot).

    preprocessor.transform() sur une seule ligne coûte ~10 ms (construction
    de DataFrame + plomberie sklearn), soit ~70 % du temps de requête
    mesuré sous charge. Cette classe précalcule les paramètres du
    transformer fitted et applique la MÊME transformation par lookups de
    dict + numpy : résultat strictement identique (vérifié par test
    d'équivalence sur le dataset), pour un coût ~50 fois moindre.

    Construite à partir de l'artefact entraîné au chargement du service :
    aucune divergence possible avec l'entraînement.
    """

    def __init__(self, column_transformer) -> None:
        scaler = column_transformer.named_transformers_["num"]
        self._num_mean = np.asarray(scaler.mean_, dtype=float)
        self._num_scale = np.asarray(scaler.scale_, dtype=float)

        ohe = column_transformer.named_transformers_["cat"]
        self._cat_index = [
            {str(value): i for i, value in enumerate(categories)}
            for categories in ohe.categories_
        ]
        sizes = [len(categories) for categories in ohe.categories_]
        self._cat_offsets = np.concatenate([[0], np.cumsum(sizes)[:-1]])
        self.n_features_out = len(NUMERIC_COLS) + int(sum(sizes))

    def transform_row(self, profile: dict) -> np.ndarray:
        """Transforme un profil brut (dict) en vecteur de features."""
        out = np.zeros(self.n_features_out)
        for j, col in enumerate(NUMERIC_COLS):
            out[j] = (_to_float(profile[col]) - self._num_mean[j]) / self._num_scale[j]
        base = len(NUMERIC_COLS)
        for j, col in enumerate(CATEGORICAL_COLS):
            idx = self._cat_index[j].get(str(profile[col]))
            # Catégorie inconnue -> colonne entièrement à zéro,
            # comme OneHotEncoder(handle_unknown="ignore").
            if idx is not None:
                out[base + self._cat_offsets[j] + idx] = 1.0
        return out
