# Architecture Decision Record

> Statut : brouillon — séance 1. Maximum 2 pages, paragraphes argumentés (pas de listes).

## 1. Cas d'usage choisi et compatibilité avec le quota

À compléter : cas retenu, estimation mémoire par service avec raisonnement explicite (type de modèle, taille des poids, concurrence estimée), démonstration que la somme des requests ne dépasse jamais le quota.

## 2. Dataset et licence

À compléter : dataset identifié, source, licence.

## 3. Communication inter-services et placement du deuxième modèle

À compléter : Services ClusterIP et DNS interne, deuxième modèle dans le service d'inférence principal ou service séparé (justification).

## 4. Outil CI/CD

À compléter : outil choisi, justification par au moins deux critères concrets.

## 5. Stratégie de déploiement

À compléter : RollingUpdate ou Recreate, avec le calcul explicite de la marge de surge disponible dans le quota (quota − somme des requests = marge).
