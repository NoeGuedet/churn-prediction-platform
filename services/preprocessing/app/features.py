"""Telco Churn feature definitions — single source of truth.

This module is imported both by the training script
(scripts/train_models.py) and by the preprocessing service, to
guarantee that the transformations applied at training time and in
production are strictly identical.
"""

import numpy as np
import pandas as pd

# Numeric columns (the load script sends strings from the CSV,
# hence the systematic coercion in prepare_frame).
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

# Feature order as expected by the preprocessor's input.
ALL_FEATURES = NUMERIC_COLS + CATEGORICAL_COLS

# The 5 fictitious offer categories.
OFFER_LABELS = [
    "discount",
    "premium_support",
    "fiber_upgrade",
    "loyalty_contract",
    "streaming_pack",
]

# Offer returned when the churn score does not exceed the threshold.
NO_OFFER = "no_offer"


def prepare_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Normalizes a raw DataFrame (CSV or JSON from the load script).

    - Coerces numeric columns to float (values arrive as strings from
      the CSV / the load script's JSON; empty fields like TotalCharges
      become NaN then 0).
    - Forces categorical columns to str.
    - Returns only the feature columns, in the expected order.
    """
    df = df.copy()
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0).astype(float)
    for col in CATEGORICAL_COLS:
        df[col] = df[col].astype(str)
    return df[ALL_FEATURES]


def _to_float(value) -> float:
    """Reproduces to_numeric(errors='coerce').fillna(0) for a scalar."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class CompiledPreprocessor:
    """Compiled version of the ColumnTransformer (StandardScaler + OneHot).

    preprocessor.transform() on a single row costs ~10 ms (DataFrame
    construction + sklearn plumbing), i.e. ~70% of the request time
    measured under load. This class precomputes the fitted transformer's
    parameters and applies the SAME transformation via dict lookups +
    numpy: strictly identical result (verified by an equivalence test
    on the dataset), for a cost ~50 times lower.

    Built from the trained artifact at service startup: no possible
    divergence from training.
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
        """Transforms a raw profile (dict) into a feature vector."""
        out = np.zeros(self.n_features_out)
        for j, col in enumerate(NUMERIC_COLS):
            out[j] = (_to_float(profile[col]) - self._num_mean[j]) / self._num_scale[j]
        base = len(NUMERIC_COLS)
        for j, col in enumerate(CATEGORICAL_COLS):
            idx = self._cat_index[j].get(str(profile[col]))
            # Unknown category -> all-zero column block,
            # like OneHotEncoder(handle_unknown="ignore").
            if idx is not None:
                out[base + self._cat_offsets[j] + idx] = 1.0
        return out
