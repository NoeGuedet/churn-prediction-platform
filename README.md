# Orchestration ML — Projet de mise en production sous contrainte

## Déploiement

> ⚠️ Section en cours de rédaction — sera complétée aux séances 2 et 3.
> À terme : les commandes exactes pour reproduire le système depuis un terminal vierge, dans l'ordre.

Prérequis :

- macOS avec Docker (daemon actif)
- minikube (`brew install minikube`)
- kubectl (`brew install kubectl`)

```bash
# Démarrer le cluster (une seule fois)
minikube start --cpus=4 --memory=6144 --driver=docker
minikube addons enable metrics-server

# Déploiement complet (séance 3)
kubectl apply -f k8s/ -n projet-NOE
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
