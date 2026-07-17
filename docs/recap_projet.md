# Récapitulatif complet du projet — orchestration ML sous contrainte

> Document de travail personnel. Objectif : maîtriser de bout en bout ce qui a été construit — les notions du cours, le code, l'infrastructure, les difficultés rencontrées et comment elles ont été résolues.
> La section **Benchmarks** sera complétée après le challenge de charge.

## Table des matières

1. [Les notions du cours, avec nos mots](#1-les-notions-du-cours-avec-nos-mots)
2. [Le projet : ce qu'on a construit](#2-le-projet--ce-quon-a-construit)
3. [Le code, service par service](#3-le-code-service-par-service)
4. [L'infrastructure : conteneurs, CI/CD, Kubernetes](#4-linfrastructure--conteneurs-cicd-kubernetes)
5. [Les difficultés rencontrées (et ce qu'elles nous ont appris)](#5-les-difficultés-rencontrées-et-ce-quelles-nous-ont-appris)
6. [Benchmarks du challenge de charge](#6-benchmarks-du-challenge-de-charge)
7. [Pour aller plus loin](#7-pour-aller-plus-loin)

---

## 1. Les notions du cours, avec nos mots

### 1.1 Kubernetes, l'essentiel

Kubernetes est un **orchestrateur déclaratif**. On ne lui dit jamais « lance ce programme » ; on écrit des fichiers YAML qui décrivent l'**état souhaité** (« il doit exister 1 pod qui fait tourner l'image X avec telles ressources »), et des contrôleurs vérifient en boucle que la réalité correspond à la déclaration. Un pod meurt → il est recréé. On change le YAML → K8s fait la transition. Tout découle de ce principe.

Notre cluster est un **minikube** : un cluster à un seul **nœud** (une VM Docker de 4 CPU / 6 Go sur le Mac). Point important mesuré en début de projet : le nœud consomme lui-même ~185m CPU / 622Mi **pour le système Kubernetes** (kubelet, API server, etcd) — c'est pour ça qu'un quota de namespace est toujours inférieur à la capacité du nœud, et qu'allouer 100 % d'un nœud à une application est une mauvaise pratique.

### 1.2 Les objets qu'on utilise

| Objet | Rôle | Chez nous |
|---|---|---|
| **Pod** | Plus petite unité : 1 conteneur qui tourne, IP éphémère | 1 pod par service |
| **Deployment** | « Il doit toujours y avoir N pods de ce type » + gère les mises à jour | 3 Deployments |
| **Service** | Nom DNS stable devant des pods éphémères. ClusterIP = interne, NodePort = exposé hors cluster | 2 ClusterIP, 1 NodePort |
| **Namespace** | Partition logique du cluster | `projet-noe` |
| **ResourceQuota** | Plafond sur la **somme** des requests/limits du namespace | 2500m / 1.5Gi |
| **LimitRange** | Valeurs par défaut + bornes min/max par conteneur | cf. `k8s/limitrange.yaml` |
| **CronJob** | Exécute un pod selon un horaire | segmentation horaire |

Pourquoi le Service est indispensable : les pods ont des IP **éphémères** (un pod recréé a une autre IP). Appeler un pod par son IP ou par `localhost` ne fonctionne pas. Le Service donne un nom DNS stable (`preprocessing-svc`) qui résout toujours vers le(s) pod(s) vivant(s). Dans le même namespace, le nom court suffit ; la forme complète est `nom.namespace.svc.cluster.local`.

### 1.3 Le trio requests / limits / réalité — le cœur du cours

Trois nombres **différents** à ne jamais confondre :

- **`requests`** = la **réservation**. Le scheduler l'utilise pour placer le pod, et le ResourceQuota la décompte. Point capital : le quota compte les requests **déclarées**, pas la consommation réelle. Un pod qui déclare 500m et consomme 50m occupe quand même 500m du quota.
- **`limits`** = le **plafond**. Ce qui se passe au dépassement dépend de la ressource (voir 1.4).
- **La consommation réelle**, mesurée par `kubectl top pods` (via metrics-server). C'est elle qui sert à calibrer les deux autres : requests ≈ 70-80 % du pic observé, limits ≈ 120-130 %.

Un ResourceQuota peut compter les requests **et** les limits (le nôtre compte les deux) — conséquence majeure vue en section 5. Et dès qu'un quota existe dans un namespace, **tout pod doit déclarer requests et limits**, sinon il est rejeté à la création : c'est à ça que sert le LimitRange (valeurs par défaut injectées automatiquement).

### 1.4 CPU vs mémoire : deux politiques d'échec

- **Le CPU est compressible** : on peut ralentir un calcul. En cas de dépassement de `limits.cpu`, le noyau applique le **throttling** : le temps est découpé en périodes de 100 ms (cgroups), le conteneur a droit à un budget de temps CPU par période (ex. `limits.cpu: 500m` → 50 ms par fenêtre de 100 ms). Budget épuisé → le processus attend la période suivante. **Rien ne plante, rien n'est logué** : la latence monte simplement, surtout en P95/P99. C'est le mode d'échec le plus difficile à détecter.
- **La mémoire est incompressible** : une fois allouée, elle est là. Dépassement de `limits.memory` → **OOMKill** : le conteneur est tué net et redémarré (`Reason: OOMKilled` dans `kubectl describe pod`). Si ça se répète → `CrashLoopBackOff` avec délai exponentiel entre redémarrages.

Lien avec le GIL Python : les threads ne parallélisent pas le calcul, donc on utilise des **workers Gunicorn = des processus**. Trop peu de workers → requêtes en file d'attente alors que le CPU est libre ; trop de workers pour le `limits.cpu` alloué → tous throttlés en même temps. Le bon réglage se mesure, il ne se devine pas.

### 1.5 RollingUpdate et le calcul de marge

Lors d'un RollingUpdate, Kubernetes démarre les nouveaux pods **avant** de terminer les anciens :

- `maxSurge: 1` → au plus 1 pod de plus que le nombre désiré pendant la transition. Le namespace héberge temporairement **2× les requests (et 2× les limits)** du service mis à jour.
- `maxUnavailable: 0` → aucun ancien pod tué avant que le nouveau soit Running. Pas de downtime, mais exige de la marge dans le quota.

Le calcul obligatoire avant de choisir la stratégie :

```
marge = quota − somme des valeurs déclarées (sur CHAQUE dimension comptée par le quota)
marge ≥ requests ET limits du plus gros pod à faire surger
```

Si la marge ne suffit pas : le nouveau pod est **rejeté par l'admission du quota** (`exceeded quota`), il reste Pending, et comme `maxUnavailable: 0` interdit de tuer l'ancien, la mise à jour est **bloquée indéfiniment** — sans que rien ne plante ni ne logue. Alternative dans ce cas : stratégie `Recreate` (tue tout puis recrée — downtime, mais aucune marge requise).

### 1.6 Multi-tenancy : ce qu'un quota fait — et ne fait pas

Un ResourceQuota est un **plafond d'admission**, pas une réservation de capacité. Scénario étudié : 2 namespaces sur 1 nœud, un avec quota, un sans. Kubernetes ne calcule **jamais** « limite du namespace sans quota = nœud − quota de l'autre ».

- À l'**ordonnancement** : le scheduler regarde la capacité non réservée du **nœud entier** (tous namespaces confondus). Un namespace sans quota peut remplir le nœud et faire échouer les pods de l'autre (`Pending`), même si son quota à lui est loin d'être atteint. Premier arrivé, premier servi.
- À l'**exécution**, ce sont les **requests des pods** qui protègent : le CPU est distribué proportionnellement aux requests (cpu.shares), et en cas de pression mémoire le kubelet évince d'abord les pods sans requests (BestEffort), puis ceux au-dessus de leurs requests (Burstable), en dernier les Guaranteed (requests = limits). Nos pods sont Burstable.

---

## 2. Le projet : ce qu'on a construit

### 2.1 Le cas d'usage

**Cas 3 — churn télécom** : pour chaque profil client, prédire un score de risque de résiliation et, si le score dépasse un seuil configurable, recommander une offre parmi 5 catégories. Contrainte métier : réponse < 200 ms. Quota imposé : **2500m CPU / 1.5Gi mémoire**.

Pourquoi ce cas : les modèles tabulaires sont légers (XGBoost ~200 Ko, RandomForest ~700 Ko), donc le défi n'est pas de faire tenir les modèles mais de **dimensionner les services HTTP** — c'est le cœur du TP, pas le ML.

### 2.2 Le flux d'une requête

```
Script de charge (profils JSON, 10 à 150 req/min)
      │  POST /predict
      ▼  (NodePort, via minikube service ou port-forward)
┌────────── namespace projet-noe — quota 2500m / 1.5Gi ──────────┐
│                                                                │
│   ┌──────────────┐  1. profil brut   ┌────────────────┐        │
│   │  inference   │ ────────────────▶ │ preprocessing  │        │
│   │  (2 modèles) │ ◀──────────────── │ /transform     │        │
│   └──────┬───────┘  2. vecteur 45    └────────────────┘        │
│          │ 3. churn_model.predict_proba → score                │
│          │ 4. si score ≥ seuil → offer_model.predict           │
│          │    sinon → "aucune_offre"                           │
│          │ 5. log (BackgroundTasks, hors chemin critique)      │
│          ▼                                                     │
│   ┌──────────────┐        ┌─────────────────────────┐          │
│   │  monitoring  │        │ CronJob segmentation    │          │
│   │  /metrics    │        │ (K-Means, 1×/heure)     │          │
│   └──────────────┘        └─────────────────────────┘          │
└────────────────────────────────────────────────────────────────┘
```

Le script de charge attend exactement `{"churn_probability": float, "recommended_offer": str}` ; seul HTTP 200 compte comme succès.

### 2.3 Les modèles

Entraînés hors cluster (`scripts/train_models.py`, reproductible avec seed fixée), artefacts versionnés dans `models/` avec fiches de validation (dataset, métrique, taille, temps d'inférence) :

| Modèle | Type | Métrique | Taille | Inférence |
|---|---|---|---|---|
| churn | XGBoost binaire | **AUC 0.838** | 209 Ko | 0.14 ms |
| offre | RandomForest 5 classes | **accuracy 0.928** | 712 Ko | ~13 ms |
| segmentation | K-Means k=4 | silhouette 0.242 | 5 Ko | batch |

Rappel sur l'AUC : le modèle sort un score, pas une classe — il faut un seuil pour décider, et l'accuracy dépend du seuil ET du déséquilibre des classes (26,5 % de churn : un prédicteur « toujours non » fait déjà 73,5 %). L'AUC mesure le **pouvoir de tri** du modèle, indépendamment du seuil : probabilité qu'un churner pris au hasard ait un score plus élevé qu'un fidèle pris au hasard. 0.5 = hasard, 1.0 = parfait. Le seuil, lui, est un paramètre d'exploitation (variable d'environnement `CHURN_THRESHOLD`).

Les 5 000 lignes synthétiques d'offres sont générées par règles métier fictives + 10 % de bruit (sinon le problème serait trivialement déterministe).

### 2.4 Décisions d'architecture majeures

- **2e modèle dans le service d'inférence** (pas de 4e pod) : un pod Python coûte ~200-250Mi de requests rien que pour son runtime (~15 % du quota) pour un modèle de 700 Ko. L'appel est synchrone et conditionnel → chaînage local, pas d'aller-retour réseau dans le budget 200 ms.
- **FastAPI + Gunicorn (workers Uvicorn)** pour les 3 services.
- **Le preprocessing est un service à part** (imposé) mais partage sa logique avec l'entraînement via `services/preprocessing/app/features.py` — **source de vérité unique** : impossible de dériver entre transformations d'entraînement et de production.

---

## 3. Le code, service par service

### 3.1 preprocessing (`services/preprocessing/`)

- Charge `preprocessor.pkl` (ColumnTransformer : StandardScaler sur 4 numériques + OneHotEncoder sur 15 catégorielles → vecteur dense de **45 features**) **au démarrage du worker**.
- `POST /transform` : valide la présence des 19 champs (422 sinon), applique `prepare_frame` (coercion des strings CSV en float, `TotalCharges: " "` → 0.0 — cas connu du dataset), transforme, renvoie `{"features": [...]}`.
- `handle_unknown="ignore"` dans le one-hot : une catégorie jamais vue en production ne plante pas le service.
- **1 seul worker Gunicorn** (voir section 5) : 175Mi mesurés.

### 3.2 inference (`services/inference/`)

- Charge les 2 modèles au démarrage. Clients HTTP **réutilisés** (pool de connexions) vers preprocessing et monitoring.
- `POST /predict` : appelle preprocessing (erreur 422 propagée, service injoignable → 503, les deux sont journalisés), calcule le score, applique le **routage conditionnel** (offre si score ≥ seuil, sinon `aucune_offre` — le modèle d'offre n'est alors *pas* appelé, testé unitairement).
- **Monitoring hors du chemin critique** : `BackgroundTasks` — la réponse HTTP part *avant* l'appel au monitoring, et une panne du monitoring ne peut jamais faire échouer une prédiction.
- 2 workers Gunicorn.

### 3.3 monitoring (`services/monitoring/`)

- `POST /log` enregistre `{ts, latency_ms, status, churn_probability, offer}` ; `GET /metrics` agrège : volume, taux d'erreur, latences avg/P95/max, requêtes de la dernière minute, 10 derniers événements.
- **Stockage borné** : `deque(maxlen=10000)` + verrou. La RAM du service est **constante** quelle que soit la durée du stress test — détail important sous quota strict.

### 3.4 segmentation (CronJob, `services/segmentation/`)

Script standalone exécuté 1×/heure : recharge `churn.csv`, applique le preprocessor partagé, recalcule le K-Means, logue silhouette + tailles des clusters sur stdout (`kubectl logs job/...`). Ne consomme des ressources que pendant le run — mais ses requests/limits s'ajoutent temporairement au quota (comptabilisé dans l'ADR).

### 3.5 Tests

17 tests, **couverture 98 %** (seuil CI : 80 %, bloquant). Couvre : les fonctions de preprocessing (coercion, TotalCharges vide, ordre des colonnes), la logique de routage (offre appelée ou non selon le seuil, avec un mock qui *échoue si le modèle d'offre est appelé à tort*), les erreurs (503, 422 propagée), un test d'intégration avec les vrais artefacts, et le monitoring (métriques, bornage, cas vide).

---

## 4. L'infrastructure : conteneurs, CI/CD, Kubernetes

### 4.1 Images Docker

- Base `python:3.14-slim` pour toutes (même version que le venv d'entraînement → compatibilité des artefacts joblib garantie ; les versions des libs sont **pinnées** dans chaque `requirements.txt`).
- `libgomp1` installé dans l'image inference (runtime OpenMP requis par XGBoost sur Debian — équivalent de `libomp` sur macOS).
- **Optimisation** : le wheel Linux d'XGBoost installe **401 Mo de librairies nvidia/CUDA** inutiles en CPU-only → installation avec `--no-deps` (numpy/scipy viennent de scikit-learn) → image inference **1.64 Go → 915 Mo**. Toutes les images < 1 Go (pas de multi-stage requis par l'énoncé).
- Contexte de build à la racine (accès à `models/`), `.dockerignore` pour exclure venv/docs/tests.
- `docker-compose.yml` : stack complète en local sans Kubernetes, validée à 100 % de succès à 300 req/min.

### 4.2 CI/CD (`.github/workflows/ci.yml`)

Pipeline GitHub Actions en 2 étages :

1. **test** : installation, `pytest` (bloque sous 80 % de couverture).
2. **build-and-push** (uniquement si tests verts) : build **multi-arch** (`linux/amd64` + `linux/arm64` via QEMU — la machine de correction peut être Intel ou Apple Silicon) des 4 images en matrice, push sur Docker Hub avec tags `1.0.0` + `latest`. Sur les pull requests, le build sert de validation mais ne pousse pas. Identifiants dans les secrets chiffrés GitHub (`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`), jamais en clair.

Un pipeline qui pousserait malgré des tests rouges serait « non fonctionnel » selon la grille — ici le build dépend explicitement du succès des tests (`needs: test`).

### 4.3 Kubernetes (`k8s/`)

Un seul `kubectl apply -f k8s/ -n projet-noe` déploie tout : namespace, quota, limitrange, 3 Deployments+Services, CronJob.

**Dimensionnement final, mesuré par `kubectl top pods`** (captures dans `docs/captures/`) :

| Service | requests CPU | requests mem | limits CPU | limits mem | Mesuré |
|---|---|---|---|---|---|
| preprocessing | 200m | 192Mi | 400m | 288Mi | 175Mi |
| inference | 450m | 448Mi | 700m | 544Mi | 250-370Mi |
| monitoring | 100m | 96Mi | 200m | 128Mi | 55-65Mi |
| **Σ permanent** | **750m** | **736Mi** | **1300m** | **960Mi** | |
| segmentation (CronJob) | 200m | 256Mi | 400m | 384Mi | ~300Mi au run |

Stratégie `RollingUpdate` (`maxSurge: 1`, `maxUnavailable: 0`) sur les 3 services. Marge de surge vérifiée sur **les deux dimensions** pour le pire cas (surge de l'inference) :

- requests : CPU 2500−750 = 1750m ≥ 450m ✓ ; mémoire 1536−736 = 800Mi ≥ 448Mi ✓
- limits : CPU 2500−1300 = 1200m ≥ 700m ✓ ; mémoire 1536−960 = 576Mi ≥ 544Mi ✓

Probes `readiness` + `liveness` sur `/health` pour chaque service. Chaque deployment expose ses URLs de voisins par variables d'environnement (`PREPROCESSING_URL=http://preprocessing-svc:8001`...).

---

## 5. Les difficultés rencontrées (et ce qu'elles nous ont appris)

### 5.1 Les noms de namespace sont en minuscules (RFC 1123)

`projet-NOE` a été rejeté par l'API (`a lowercase RFC 1123 label must consist of lower case...`) — et comme la création du namespace a échoué, **toutes** les autres ressources ont échoué en cascade (`namespace not found`). Correction : `projet-noe`.

### 5.2 La course d'initialisation du namespace

Après correction, le namespace a été créé mais les ressources appliquées dans la foulée ont été rejetées par l'admission controller le temps qu'il devienne *Active*. L'apply est **idempotent** : ré-exécuter la même commande fait converger. C'est documenté dans le README pour la machine de correction.

### 5.3 preprocessing au-dessus de ses requests

Mesuré à **305Mi** avec 2 workers Gunicorn (chacun charge pandas + sklearn, ~150Mi) pour des requests de 256Mi → risque d'OOMKill sous charge. Plutôt que d'augmenter les requests, on a réduit à **1 worker** (une transformation = 5-10 ms de CPU, très en dessous de 150 req/min) → **175Mi mesurés**. Leçon : sous quota strict, on optimise la consommation avant d'augmenter le budget.

### 5.4 Le rollout bloqué — la leçon principale du TP

Après le passage à 1 worker, le RollingUpdate du preprocessing est resté figé : `ReplicaFailure / FailedCreate` avec le message `exceeded quota: ... limits.memory=384Mi, used: 1344Mi, limited: 1536Mi`. **La marge des requests suffisait (896+256 ≤ 1536), mais pas celle des limits (1344+384 > 1536)** : notre quota compte les deux dimensions, et le calcul de surge de l'ADR n'en vérifiait qu'une. Pire : un surge de l'inference échouait aussi sur le CPU limits (1800+1000 > 2500). Avec ces valeurs, **aucun RollingUpdate n'était possible**.

Correction : rééquilibrage complet du budget (limits resserrées à ~120-150 % du pic mesuré) jusqu'à ce que les **4 inégalités** (requests et limits × CPU et mémoire) tiennent pour le pire cas. Validé ensuite par un `kubectl rollout restart` réussi. L'ADR raconte cette correction — c'est exactement le type de justification attendue à l'oral.

### 5.5 Le deadlock du changement de budget à chaud

Subtilité découverte en appliquant la correction : les **anciens** pods (aux anciennes limits généreuses) occupaient encore le quota (1344Mi), donc les **nouveaux** pods plus sobres ne pouvaient pas surger non plus — et `maxUnavailable: 0` interdisait de tuer les anciens avant. Impasse, résolue en recréant les deployments (acceptable en dev ; sur un cluster vierge — le cas de la correction — le problème ne se pose pas puisque les valeurs finales sont appliquées directement).

### 5.6 Les 401 Mo de CUDA dans XGBoost

Image inference initiale : 1.64 Go. Inspection → le wheel Linux d'XGBoost dépend de librairies `nvidia` (GPU) de 401 Mo, inutiles en inférence CPU. Fix : `--no-deps`. Leçon générale : inspecter ses images (`du -sh site-packages/*`) plutôt que d'accepter leur taille.

---

## 6. Benchmarks du challenge de charge

Protocole exécuté (`scripts/run_challenge.sh`) : 3 niveaux de 5 min (nominal 10 req/min, charge 50, stress 150), relevés `kubectl top pods` toutes les 30 s + métriques du monitoring avant/après. Captures brutes dans `docs/captures/challenge_*.txt`.

### 6.1 Résultats des 3 niveaux (avant correction)

| Niveau | Succès | Latence moy / P95 (client) | CPU max observé | Mémoire max | Restarts |
|---|---|---|---|---|---|
| Nominal (10/min) | 50/50 — 100 % | 36 ms / 40 ms | inference 8m, preprocessing 6m | inference 252Mi | 0 |
| Charge (50/min) | 250/250 — 100 % | 34 ms / 39 ms | inference 12m, preprocessing 15m | inference 255Mi | 0 |
| Stress (150/min) | 744/745 — 99,9 % | 33 ms / 39 ms | inference 22m, preprocessing 35m | inference 255Mi | 0 |

Vue serveur (monitoring, niveau stress) : **0 échec**, latence moyenne **15,5 ms**, P95 20,4 ms.

### 6.2 Lecture des résultats

- **Aucune saturation** : la latence est plate d'un niveau à l'autre, le CPU reste sous 10 % des limits partout (inference 22m pour 700m autorisés), la mémoire est stable → ni throttling ni OOMKill, dimensionnement validé avec marge.
- **L'échec unique au stress est côté client** (0 échec dans le monitoring) : artefact du tunnel port-forward, pas du système.
- **Enseignement clé** : le service le plus coûteux en CPU par requête n'est PAS l'inférence mais le **preprocessing** (35m vs 22m au stress). La cause n'est pas la transformation elle-même mais la **plomberie pandas/sklearn sur une seule ligne** : mesuré, `/transform` prenait ~10,8 ms des ~15 ms de temps serveur (~70 %).

### 6.3 Correction identifiée et appliquée

**Correction : compiler le preprocessor.** Un `ColumnTransformer` (StandardScaler + OneHotEncoder) est une transformation déterministe : on précalcule ses paramètres à partir de l'artefact fitted et on l'applique par lookups de dict + numpy (`CompiledPreprocessor` dans `features.py`), sans reconstruction de DataFrame ni validation sklearn à chaque appel. Sécurisée par un **test d'équivalence stricte** contre le transformer d'origine sur 200 profils réels + cas limites (TotalCharges vide, catégorie inconnue) — aucune divergence possible avec l'entraînement.

### 6.4 Avant / après (mesures)

| Métrique | Avant | Après | Effet |
|---|---|---|---|
| `/transform` moyenne | 10,8 ms | 5,2 ms | **−52 %** |
| `/transform` P95 | 29,5 ms | 6,4 ms | **−78 %** |
| Stress 150 req/min — succès | 99,9 % (744/745) | **100 % (745/745)** | |
| Stress — latence moy / P95 (client) | 33 / 39 ms | **23 / 29 ms** | **−30 % / −26 %** |
| Stress — latence moy serveur (monitoring*) | 15,5 ms | ≈ 6 ms | **−60 %** |
| Stress — CPU preprocessing max | 35m | **9m** | **−74 %** |

\* latence serveur après correction estimée par différence des moyennes cumulées du monitoring sur la fenêtre de test.

Le reste du surcoût de `/transform` après correction (~5 ms) est l'overhead HTTP/uvicorn à travers le port-forward, pas la transformation elle-même (~0,2 ms mesurée). Fait marquant : le CronJob de segmentation s'est exécuté **pendant** le stress post-correction (planification horaire) — 0 échec malgré ses 384Mi de limits ajoutées temporairement au quota.

---

## 7. Pour aller plus loin

### 7.1 File de messages + batch inference

**Le constat** : aujourd'hui chaque requête HTTP déclenche une inférence synchrone individuelle (1 ligne à la fois). Sous pic de charge, le coût fixe par requête (appel HTTP au preprocessing, overheads Python, appels `predict_proba` ligne par ligne) ne s'amortit pas, et les workers doivent être dimensionnés pour le pic.

**L'architecture cible** : l'API HTTP devient un simple **producteur** qui pousse les profils dans une **file de messages** et répond immédiatement avec un identifiant (pattern asynchrone), ou attend le résultat avec un timeout court. Un pool de **workers consommateurs** tire les messages **par lots** (batch de N) et appelle `predict_proba` sur une **matrice de N lignes** en une seule fois — l'inférence vectorisée est beaucoup plus efficace que N appels unitaires (coûts fixes amortis, meilleure utilisation CPU).

**Le compromis, bien compris** : le batching **réduit la latence en pic** (le goulot d'étranglement CPU est lissé, le débit monte, les P95/P99 descendent) **au prix d'un peu de latence au repos** : à faible trafic, une requête peut attendre que la fenêtre de batch se remplisse (ou expire, typiquement 20-100 ms) avant d'être traitée. En charge, la fenêtre se remplit instantanément, donc aucune attente supplémentaire. Pour notre cas précis (XGBoost à ~0,14 ms/ligne), le gain serait modeste ; pour un modèle lourd (CNN, GPU), c'est l'architecture standard.

### 7.2 Pourquoi SQS plutôt que Redis (dans notre contexte)

Les deux remplissent le rôle de file, mais pas avec le même modèle :

- **SQS (AWS)** est **managé** : aucun broker à installer, patcher, surveiller ou dimensionner — et surtout **aucune empreinte dans notre quota** de 1.5 Gi. Sémantique de livraison *at-least-once* avec *visibility timeout* (un message non acquitté réapparaît → pas de perte si un worker meurt en plein traitement), **DLQ** native pour les messages en échec, coût à l'usage qui tombe à zéro quand il n'y a pas de trafic. Un contenu de file devient aussi une **métrique d'autoscaling** (KEDA peut scaler les workers de 0 à N selon la profondeur de la file).
- **Redis** (auto-hébergé dans le cluster, ou ElastiCache) est excellent en latence (sous la milliseconde) et ses Streams offrent une sémantique proche, mais : c'est un **service stateful de plus à opérer** dans le cluster (RAM, persistance, failover), sa RAM se décompte de notre quota, et en mode pub/sub simple la livraison est *fire-and-forget* (un consommateur absent perd les messages — il faut passer aux Streams + consumer groups pour la durabilité, donc plus de complexité).

Pour un TP dont le sujet est « tenir sous contrainte de ressources », externaliser l'état de la file chez un service managé est cohérent : on dépense notre budget mémoire pour ce qui produit de la valeur (l'inférence), pas pour de la plomberie. En production AWS réelle, on ajouterait KEDA (autoscaling sur profondeur de file) et un API Gateway devant.

### 7.3 Autres pistes

- **HPA** (Horizontal Pod Autoscaler) : scaler le nombre de replicas de l'inference sur le CPU mesuré au lieu du dimensionnement statique — la suite naturelle de ce TP (attention : le quota borne le nombre de pods, le calcul de marge reste nécessaire).
- **Prometheus + Grafana** à la place du monitoring maison : compteurs de throttling (`container_cpu_cfs_throttled_periods_total`) directement visibles, alertes, dashboards.
- **VPA** (Vertical Pod Autoscaler) en mode recommandation : suggère les requests/limits à partir de l'historique — industrialise ce qu'on a fait à la main avec `kubectl top`.

---

*Document rédigé au fil du projet. Dernière mise à jour : après la séance 4 (challenge de charge + correction mesurée).*

---

## 8. Plan de slides pour la présentation (partie 1 de l'oral, 5-7 min)

> Consignes pour générer les slides : ~13 slides (≈30 s chacune), dans l'ordre chronologique du projet. Chaque slide cite ses chiffres exacts — tous sont mesurés et sourcés (captures dans `docs/captures/`, fiches dans `models/README.md`). Support visuel exigé par l'énoncé : diagramme d'architecture + tableau de dimensionnement (slides 4 et 9).

### Slide 1 — Titre
- Titre : « Mise en production d'un pipeline ML sous contrainte de ressources »
- Sous-titre : Cas 3 — prédiction de churn télécom & recommandation d'offre. Namespace `projet-noe`, quota 2500m CPU / 1.5Gi.

### Slide 2 — Contexte et cas d'usage
- Métier : un opérateur télécom veut scorer le risque de résiliation d'un client et proposer une offre ciblée, en **moins de 200 ms**.
- Le correcteur clone le repo, lance UNE commande de déploiement, puis un script de charge aux 3 niveaux (10, 50, 150 req/min × 5 min) sur sa machine. Aucune intervention manuelle tolérée.
- Endpoint évalué : `POST /predict` → `{"churn_probability": 0.74, "recommended_offer": "remise_tarifaire"}`.
- Dataset : Telco Customer Churn (IBM), 7 043 clients, 21 variables, 26,5 % de churn — licence publique.

### Slide 3 — Contraintes imposées
- Quota non négociable : **2500m CPU / 1.5Gi mémoire** (le plus serré des 3 cas).
- 3 services obligatoires : preprocessing, inference, monitoring — + 2 modèles entraînés par nous.
- CI/CD : tests bloquants à 80 % de couverture, images sur Docker Hub.
- Défi spécifique du cas 3 : dimensionner les workers HTTP face à la latence d'inférence à 150 req/min.
- Le point de vue du projet : le ML est facile, la difficulté est de **tenir la charge dans un budget strict et de le prouver par des mesures**.

### Slide 4 — Architecture (slide diagramme — obligatoire)
- Reproduire le schéma de la section 2.2 : script → `inference-svc` (NodePort) → `preprocessing-svc` (ClusterIP) → inference (2 modèles, routage par seuil) → `monitoring-svc` (ClusterIP) ; CronJob horaire.
- Points à annoter : 2e modèle **dans** l'inference (un pod Python de plus = ~200-250Mi, soit ~15 % du quota, pour 712 Ko de modèle) ; monitoring **hors du chemin critique** (BackgroundTasks) ; stockage monitoring **borné** (deque 10 000) → RAM constante.
- Communication : DNS interne Kubernetes (`http://preprocessing-svc:8001`), jamais d'IP de pod.

### Slide 5 — Les modèles et leurs métriques
| Modèle | Type | Métrique | Taille | Inférence |
|---|---|---|---|---|
| Churn | XGBoost | **AUC 0.838** (acc 0.801) | 209 Ko | 0,14 ms |
| Offre (5 classes) | RandomForest | **accuracy 0.928** | 712 Ko | ~13 ms |
| Segmentation | K-Means k=4 | silhouette 0.242 | 5 Ko | batch horaire |
- Pourquoi l'AUC : dataset déséquilibré (26,5 % de churn) — un prédicteur « toujours non » a déjà 73,5 % d'accuracy. L'AUC mesure le pouvoir de tri indépendamment du seuil.
- Seuil de déclenchement de l'offre **configurable** (env `CHURN_THRESHOLD`, défaut 0,5).
- Données d'offre : 5 000 lignes synthétiques par règles métier + 10 % de bruit.
- Anecdote chiffrée : le modèle d'offre est passé de **19 Mo à 712 Ko** en resserrant les hyperparamètres — avec une accuracy *meilleure* (0,918 → 0,928).

### Slide 6 — Zéro dérive entraînement / production
- `features.py` : module unique importé par l'entraînement ET par le service preprocessing (coercion des types, 19 champs → 45 features, `TotalCharges: " "` → 0.0).
- Preprocessor fit **sur le train split uniquement** (pas de fuite) ; `handle_unknown="ignore"` → une catégorie inconnue en prod ne plante pas.
- Artefacts rechargés avec les **versions pinnées** des libs (sklearn 1.9.0, XGBoost 3.3.0).

### Slide 7 — Conteneurisation
- 3 Dockerfiles + docker-compose ; stack validée : **100 % de succès à 300 req/min**, latence ~28 ms.
- Images : inference **915 Mo** (1,64 Go initialement — le wheel XGBoost embarquait **401 Mo de libs CUDA inutiles**, éliminées via `--no-deps`), preprocessing 719 Mo, monitoring 244 Mo. Toutes < 1 Go.
- Base `python:3.14-slim` + `libgomp1` (OpenMP pour XGBoost), versions pinnées partout.

### Slide 8 — Pipeline CI/CD
- 2 étages : **test** (pytest, couverture bloquante ≥ 80 % — mesurée à **97 %**, 18 tests) → **build-and-push** uniquement si tests verts (`needs: test`).
- Build **multi-arch** (amd64 + arm64, QEMU) → la machine de correction marche quelle que soit son architecture.
- 4 images sur Docker Hub (`noeguedet/orchestration-ml-*`, tags `1.0.0` + `latest`) ; identifiants en secrets GitHub chiffrés.
- Validé de bout en bout : images supprimées du cluster → pods pullés depuis Docker Hub → système fonctionnel.

### Slide 9 — Dimensionnement Kubernetes (tableau — obligatoire)
| Service | requests | limits | Mesuré `kubectl top` |
|---|---|---|---|
| preprocessing | 200m / 192Mi | 400m / 288Mi | 175Mi |
| inference | 450m / 448Mi | 700m / 544Mi | 250-370Mi |
| monitoring | 100m / 96Mi | 200m / 128Mi | 55-65Mi |
| **Σ** | **750m / 736Mi** | **1300m / 960Mi** | quota 2500m / 1536Mi |
- Calibration par la mesure : preprocessing **2 workers → 1 worker** (305Mi → 175Mi) plutôt que d'augmenter les requests.
- Rappel de cours : le quota compte les requests **déclarées**, pas la conso réelle ; le nœud consomme lui-même ~185m / 622Mi (mesuré).

### Slide 10 — RollingUpdate : la leçon du projet
- Stratégie : `RollingUpdate` `maxSurge: 1`, `maxUnavailable: 0` (zéro downtime, même en démo).
- **L'incident** : premier rollout bloqué — `exceeded quota: limits.memory=384Mi, used: 1344Mi, limited: 1536Mi`. La marge des requests suffisait, pas celle des **limits** : le quota compte les DEUX dimensions.
- **La correction** : limits resserrées à ~120-150 % du pic mesuré, jusqu'aux 4 inégalités vérifiées pour le pire cas (surge inference) : requests CPU 1750m ≥ 450m, requests mem 800Mi ≥ 448Mi, limits CPU 1200m ≥ 700m, limits mem 576Mi ≥ 544Mi.
- **Validé** par un `kubectl rollout restart` réussi juste après.
- Point de vigilance documenté : rollout pendant l'exécution du CronJob → marge limits.mem insuffisante (960+384+544 > 1536) → rollouts hors fenêtre du CronJob.

### Slide 11 — Challenge de charge (3 niveaux imposés)
| Niveau | Succès | Latence moy / P95 | CPU max | Restarts |
|---|---|---|---|---|
| Nominal (10/min) | 100 % (50/50) | 36 / 40 ms | inference 8m | 0 |
| Charge (50/min) | 100 % (250/250) | 34 / 39 ms | inference 12m | 0 |
| Stress (150/min) | 99,9 % (744/745) | 33 / 39 ms | preprocessing 35m | 0 |
- Latence **plate** sur les 3 niveaux, CPU < 10 % des limits, mémoire stable → ni throttling ni OOMKill.
- L'unique échec est côté client (tunnel port-forward) : **0 échec côté serveur** (monitoring : 1 045 requêtes, 15,5 ms moy. au stress).

### Slide 12 — La correction mesurée avant/après
- Diagnostic : le preprocessing est le 1er consommateur CPU par requête (35m vs 22m inference) — `/transform` = **10,8 ms** sur ~15 ms de temps serveur (~70 %) : plomberie pandas/sklearn sur 1 ligne.
- Correction : `CompiledPreprocessor` — le ColumnTransformer est compilé en lookups + numpy depuis l'artefact fitted. **Équivalence stricte prouvée par test** (200 profils réels + cas limites).
| Métrique | Avant | Après | Effet |
|---|---|---|---|
| `/transform` moyenne | 10,8 ms | 5,2 ms | **−52 %** |
| `/transform` P95 | 29,5 ms | 6,4 ms | **−78 %** |
| Stress 150/min — succès | 99,9 % | **100 %** (745/745) | |
| Stress — latence moy / P95 (client) | 33 / 39 ms | **23 / 29 ms** | **−30 % / −26 %** |
| Stress — CPU preprocessing max | 35m | **9m** | **−74 %** |
- Méthode : mesurer → identifier le goulot → corriger → re-mesurer (protocole `scripts/run_challenge.sh`).
- Fait marquant : le CronJob s'est exécuté **pendant** le stress post-correction → 0 échec malgré la pointe temporaire de quota (calcul de l'ADR vérifié en conditions réelles).

### Slide 13 — Pour aller plus loin
- **File SQS + batch inference** : l'API produit dans une file managée (zéro empreinte dans le quota, at-least-once + DLQ, scale-to-zero) ; des workers consomment **par lots** → `predict_proba` vectorisé sur N lignes. Effet : latence en pic **réduite** (CPU lissé, débit ↑) au prix d'une latence au repos légèrement **augmentée** (fenêtre de batch, ~20-100 ms à faible trafic).
- **Pourquoi SQS plutôt que Redis** : managé (pas de broker stateful à opérer dans le cluster, pas de RAM prélevée sur les 1.5 Gi), DLQ native, métrique de profondeur directement autoscaling-ready (KEDA). Redis = excellent en latence mais c'est un état à gérer et à loger dans le quota.
- **HPA** : autoscaling des replicas sur CPU (le quota borne le nb de pods — le calcul de marge reste nécessaire).
- **Prometheus** : compteurs de throttling natifs (`container_cpu_cfs_throttled_periods_total`) au lieu du monitoring maison.

### Slide 14 — Démo (transition vers la partie 2)
- Ce qui sera montré : `kubectl get all -n projet-noe` (pods Running), une requête `/predict` en direct, `curl /metrics` du monitoring, et si le temps le permet un `rollout restart` (surge validé en direct).
- Repo : `github.com/NoeGuedet/orchestration_ml` — déploiement : `kubectl apply -f k8s/ -n projet-noe`.
