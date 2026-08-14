#!/usr/bin/env python3
"""Analysis of the churn model decision threshold.

Plots precision / recall / F1 as a function of the threshold applied to
the XGBoost score, on the same test split as training (random_state=42).
Produces docs/images/churn_threshold.png (used in the slides) and prints
the F1-optimal threshold.

Usage: .venv/bin/python scripts/analyze_threshold.py
"""

import sys
from pathlib import Path

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).parent.parent))
from services.preprocessing.app.features import prepare_frame  # noqa: E402

DATA_PATH = Path(__file__).parent.parent / "data" / "churn.csv"
MODELS_DIR = Path(__file__).parent.parent / "models"
OUT_PATH = Path(__file__).parent.parent / "docs" / "images" / "churn_threshold.png"
RANDOM_STATE = 42
DEPLOYED_THRESHOLD = 0.5


def main() -> None:
    raw = pd.read_csv(DATA_PATH)
    y = (raw["Churn"] == "Yes").astype(int).to_numpy()
    X = prepare_frame(raw)

    preprocessor = joblib.load(MODELS_DIR / "preprocessor.pkl")
    churn_model = joblib.load(MODELS_DIR / "churn_model.pkl")

    _, X_test, _, y_test = train_test_split(
        X, y, test_size=0.2, stratify=y, random_state=RANDOM_STATE
    )
    proba = churn_model.predict_proba(preprocessor.transform(X_test))[:, 1]

    thresholds = np.arange(0.05, 0.96, 0.01)
    precisions, recalls, f1s = [], [], []
    for t in thresholds:
        pred = (proba >= t).astype(int)
        precisions.append(precision_score(y_test, pred, zero_division=0))
        recalls.append(recall_score(y_test, pred, zero_division=0))
        f1s.append(f1_score(y_test, pred, zero_division=0))

    best_idx = int(np.argmax(f1s))
    best_t, best_f1 = thresholds[best_idx], f1s[best_idx]
    deployed_f1 = f1_score(y_test, (proba >= DEPLOYED_THRESHOLD).astype(int))
    print(f"Deployed threshold {DEPLOYED_THRESHOLD}: F1={deployed_f1:.3f}")
    print(
        f"F1-optimal threshold: {best_t:.2f} "
        f"(F1={best_f1:.3f}, precision={precisions[best_idx]:.3f}, "
        f"recall={recalls[best_idx]:.3f})"
    )

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(thresholds, precisions, label="Precision", linewidth=2)
    ax.plot(thresholds, recalls, label="Recall", linewidth=2)
    ax.plot(thresholds, f1s, label="F1", linewidth=2)
    ax.axvline(
        DEPLOYED_THRESHOLD, color="gray", linestyle="--",
        label=f"Deployed threshold ({DEPLOYED_THRESHOLD})",
    )
    ax.axvline(
        best_t, color="green", linestyle=":",
        label=f"F1 optimum ({best_t:.2f})",
    )
    ax.set_xlabel("Decision threshold (churn score)")
    ax.set_ylabel("Metric")
    ax.set_title("Churn XGBoost — metrics vs threshold (test split)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(OUT_PATH, dpi=150)
    print(f"Plot saved: {OUT_PATH}")


if __name__ == "__main__":
    main()
