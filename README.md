# Orchestration ML — Projet de mise en production sous contrainte

## Déploiement

### Option A — Docker Compose (local, sans Kubernetes)

```bash
git clone git@github.com:NoeGuedet/orchestration_ml.git
cd orchestration_ml
docker compose up --build -d
```

Vérification :

```bash
curl http://localhost:8002/health          # inference
curl http://localhost:8003/metrics         # monitoring
```

### Option B — Kubernetes (minikube)

Prérequis :

- macOS avec Docker (daemon actif)
- minikube (`brew install minikube`)
- kubectl (`brew install kubectl`)

```bash
# Démarrer le cluster (une seule fois)
minikube start --cpus=4 --memory=6144 --driver=docker
minikube addons enable metrics-server

# Déploiement complet (séance 3)
kubectl apply -f k8s/ -n projet-noe
```

Note : sur un cluster vierge, si certaines ressources signalent `namespace not found` (le namespace est en cours d'initialisation), ré-exécuter la même commande — elle est idempotente.

### Exposer le service d'inférence

```bash
# Option 1 — minikube service (garde le terminal ouvert)
minikube service inference-svc -n projet-noe --url

# Option 2 — port-forward (utilisé pour nos tests)
kubectl port-forward svc/inference-svc 8002:8002 -n projet-noe &
# URL : http://localhost:8002/predict
```

### Test de charge

```bash
pip install requests
python scripts/load_test.py --case churn --level nominal --url http://localhost:8002/predict
# niveaux : nominal (10/min), charge (50/min), stress (150/min), extreme (--rate libre)
```

Métriques en direct pendant le test :

```bash
kubectl top pods -n projet-noe                                  # conso réelle
kubectl port-forward svc/monitoring-svc 8003:8003 -n projet-noe &
curl http://localhost:8003/metrics                              # volume, latence, taux d'erreur
```

### Tests

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt -r services/preprocessing/requirements.txt -r services/inference/requirements.txt
pytest            # couverture >= 80 % exigée
```

## Présentation

Pipeline ML multi-services déployé sur Kubernetes (minikube) sous quota de ressources non négociable :

- **preprocessing** : réception et préparation des données brutes
- **inference** : API REST de prédiction (modèles entraînés pour le projet)
- **monitoring** : enregistrement des requêtes/prédictions, métriques (volume, latence, taux d'erreur)

## Structure du repo

```
├── .github/workflows/   # Pipeline CI/CD
├── scripts/             # Script de charge officiel (load_test.py)
├── data/                # Données du script de charge
├── models/              # Artefacts des modèles + fiches de validation
├── services/            # preprocessing / inference / monitoring
├── k8s/                 # Manifests Kubernetes (quota, limitrange, services)
├── tests/               # Tests (couverture ≥ 80 %)
├── docs/                # Documents du cours (PDF + conversions markdown)
├── ADR.md               # Architecture Decision Record
└── README.md
```
