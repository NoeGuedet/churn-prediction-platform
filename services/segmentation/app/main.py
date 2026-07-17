"""Job de segmentation K-Means — exécuté par le CronJob Kubernetes.

Recharge le dataset, applique le preprocessor partagé, recalcule la
segmentation K-Means et journalise le résultat sur stdout (consultable
via `kubectl logs job/...`). Conçu pour une exécution courte et ponctuelle :
les ressources ne sont consommées que pendant le run (cf. ADR, section 5).
"""

from pathlib import Path

import joblib
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from features import prepare_frame

BASE_DIR = Path(__file__).parent.parent
DATA_PATH = BASE_DIR / "data" / "churn.csv"
MODELS_DIR = BASE_DIR / "models"


def main() -> None:
    preprocessor = joblib.load(MODELS_DIR / "preprocessor.pkl")
    raw = pd.read_csv(DATA_PATH)
    X = preprocessor.transform(prepare_frame(raw))

    kmeans = KMeans(n_clusters=4, n_init=10, random_state=42)
    labels = kmeans.fit_predict(X)
    silhouette = silhouette_score(X, labels, sample_size=2000, random_state=42)
    sizes = pd.Series(labels).value_counts().sort_index().to_dict()

    print(f"[SEGMENTATION] {len(X)} clients segmentés en 4 clusters")
    print(f"[SEGMENTATION] silhouette={silhouette:.3f}  tailles={sizes}")


if __name__ == "__main__":
    main()
