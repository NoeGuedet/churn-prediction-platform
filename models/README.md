# Modèles

Fiches de validation des modèles du cas 3 (churn télécom). Entraînement reproductible via `scripts/train_models.py` (graine fixée, `random_state=42`).

Environnement d'entraînement : Python 3.14, scikit-learn 1.9.0, XGBoost 3.3.0, pandas 3.0.3. **Ces versions sont pinnées dans les images Docker des services** — un artefact joblib n'est garanti de se recharger qu'avec la même version de la bibliothèque qui l'a produit.

## Modèle 1 — Score de churn (`churn_model.pkl`)

- Dataset : Telco Customer Churn (IBM), 7 043 lignes, split 80/20 stratifié sur la cible
- Type : XGBoost binaire (`XGBClassifier`, 300 arbres, profondeur 5), `predict_proba` → score entre 0 et 1
- Métrique principale : **AUC = 0.838** (accuracy 0.801, F1 0.588 au seuil 0.5 — dataset déséquilibré à 26.5 % de churn, d'où l'AUC comme métrique de référence)
- Taille de l'artefact : 209 Ko
- Temps d'inférence moyen (local, Apple Silicon) : **0.14 ms/ligne**

## Modèle 2 — Recommandation d'offre (`offer_model.pkl`)

- Dataset : 5 000 lignes synthétiques dérivées du dataset Telco (labels générés par règles métier fictives + 10 % de bruit, 5 catégories d'offres), split 80/20
- Type : RandomForest multiclasses (100 arbres, profondeur 8, `min_samples_leaf=5`)
- Métrique principale : **accuracy = 0.928** (F1-macro 0.792 ; le plafond théorique est ~0.90 hors bruit, le modèle apprend aussi une partie du bruit)
- Taille de l'artefact : 712 Ko
- Temps d'inférence moyen (local) : **13.2 ms/ligne** (`predict_proba` ; `predict` seul, utilisé en production, est plus rapide)

## Modèle 3 — Segmentation K-Means (`kmeans_model.pkl`, optionnel, CronJob)

- Dataset : Telco Customer Churn complet, features transformées (même preprocessor que les deux autres modèles)
- Type : K-Means, k=4
- Métrique : silhouette = 0.242 ; tailles des clusters : 1976 / 2621 / 1526 / 920
- Taille de l'artefact : 5 Ko
- Usage : recalcul planifié de la segmentation en CronJob Kubernetes (hors chemin synchrone)

## Préprocessing partagé (`preprocessor.pkl`)

- `ColumnTransformer` : `StandardScaler` sur 4 colonnes numériques + `OneHotEncoder(handle_unknown="ignore")` sur 15 colonnes catégorielles → vecteur dense de **45 features**
- Fit sur le train split uniquement (pas de fuite de données)
- Taille : 2 Ko
- Chargé par le service **preprocessing** en production ; les définitions de colonnes et la coercion des types sont dans `services/preprocessing/app/features.py`, module importé à la fois par l'entraînement et par le service (source de vérité unique)
