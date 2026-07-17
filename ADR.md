# Architecture Decision Record

Cas d'usage 3 — Prédiction de churn et recommandation d'offre. Namespace `projet-noe` (les noms de namespaces Kubernetes doivent être en minuscules, RFC 1123). Quota imposé : **2500m CPU / 1.5Gi mémoire**, non négociable.

## 1. Cas d'usage choisi et compatibilité avec le quota

Nous avons choisi le cas 3, prédiction de churn et recommandation d'offre pour un opérateur télécom, avec une contrainte métier de réponse en moins de 200 ms. Ce choix est compatible avec le quota imposé pour une raison structurelle : les deux modèles à servir sont des modèles tabulaires légers (un XGBoost d'environ 20 Mo pour le score de churn, un classifieur multiclasses de quelques Mo pour la recommandation d'offre), donc la mémoire n'est pas consommée par les poids des modèles mais par les runtimes Python des services. Le défi de ce cas n'est pas de faire tenir les modèles, mais de dimensionner correctement les workers HTTP des services face à la latence d'inférence à 150 req/min, sans gaspiller des requests dans un quota mémoire de seulement 1.5 Gi.

Le raisonnement de dimensionnement suit la nature de chaque service. Le preprocessing ne charge aucun modèle : il applique des transformations tabulaires (encodage des variables catégorielles, mise à l'échelle) dont le coût est surtout du CPU en pics courts, avec une mémoire modeste et stable que nous estimons à 200-250 Mi. L'inférence charge ses deux modèles au démarrage — le pic de mémoire a lieu au chargement des poids, pas sous charge — et consomme ensuite le runtime Python/scikit-learn/XGBoost, soit environ 400-500 Mi au total. Le monitoring ne fait que compter et stocker des métriques en mémoire ; sa consommation de base est faible (environ 130 Mi) et ne croît que lentement avec le volume de requêtes enregistrées. Le CronJob de segmentation, lui, ne consomme que pendant son exécution (quelques minutes par heure) mais ses requests s'ajoutent temporairement au quota pendant ce laps de temps.

Ces estimations ont ensuite été confrontées aux mesures réelles (`kubectl top pods`) en séance 3, et le dimensionnement final est le suivant :

| Service | requests CPU | requests mémoire | limits CPU | limits mémoire | Mesuré (`kubectl top`) |
|---|---|---|---|---|---|
| preprocessing (1 worker) | 200m | 192Mi | 400m | 288Mi | 175Mi |
| inference | 450m | 448Mi | 700m | 544Mi | 250-370Mi |
| monitoring | 100m | 96Mi | 200m | 128Mi | 55-65Mi |
| segmentation (CronJob) | 200m | 256Mi | 400m | 384Mi | ~300Mi pendant le run |

La somme des requests permanents est de **750m CPU / 736Mi** (30 % et 48 % du quota), la somme des limits de **1300m / 960Mi**. Deux calibrations issues de la mesure méritent d'être consignées. D'abord, le preprocessing mesuré à 305Mi avec 2 workers Gunicorn (chacun charge pandas + scikit-learn, ~150Mi) dépassait ses requests de 256Mi : comme une transformation ne coûte que 5-10 ms de CPU, nous sommes passés à **un seul worker** — 175Mi mesurés — plutôt que d'augmenter les requests, conformément à la discipline du quota. Ensuite, les valeurs mesurées ont permis de resserrer les limits à ~120-150 % du pic observé, ce qui s'est révélé indispensable pour la section 5.

## 2. Dataset et licence

Le dataset retenu est Telco Customer Churn, publié par IBM comme jeu de données d'exemple : 7 043 clients décrits par 21 variables (données contractuelles, services souscrits, facturation), pour un CSV d'environ 950 Ko. Il est librement redistribué — on le trouve sur le GitHub d'IBM, sur Kaggle et dans l'UCI ML Repository — ce qui garantit sa réutilisabilité dans le cadre du projet. Le fichier est versionné dans `data/churn.csv` et sert à la fois à l'entraînement du modèle de churn et au script de charge. Pour le modèle de recommandation d'offre, nous générerons 5 000 lignes synthétiques dérivées de ce même dataset, avec 5 catégories d'offres fictives, conformément à l'énoncé.

## 3. Communication inter-services et placement du deuxième modèle

Les trois services communiquent par le réseau interne du cluster via des objets Service de type ClusterIP, qui fournissent un nom DNS stable indépendant des IP éphémères des pods. Le flux d'une requête est le suivant : le script de charge appelle `POST /predict` sur le service d'inférence, exposé hors du cluster par `minikube service` ; l'inférence transmet le profil client brut au service de preprocessing (`http://preprocessing-svc:8001/transform`), qui applique les transformations et renvoie le vecteur de features ; l'inférence calcule le score de churn, appelle le modèle de recommandation si le score dépasse le seuil configuré, puis notifie le service de monitoring (`http://monitoring-svc:8003/log`) qui enregistre la requête, la prédiction et la latence. Le monitoring expose ses métriques (volume, latence, taux d'erreur) sur un endpoint dédié, consultable pendant les tests par `kubectl port-forward`.

Le deuxième modèle vit dans le service d'inférence principal, et non dans un quatrième service dédié. La justification est d'abord une question de quota : un pod Python supplémentaire coûterait 200 à 250 Mi de requests rien que pour son runtime, soit environ 15 % du quota mémoire, pour y héberger un modèle de quelques mégaoctets — un gaspillage que le quota de 1.5 Gi ne permet pas. La justification est aussi fonctionnelle : l'appel au modèle d'offre est synchrone et conditionnel (uniquement si le score de churn dépasse le seuil), donc le chaîner en local évite un aller-retour réseau dans un budget latence de 200 ms. Le compromis accepté est que les deux modèles sont déployés ensemble : une mise à jour de l'un redéploie l'autre, ce qui est acceptable ici puisque les deux artefacts évoluent rarement et que le RollingUpdate (section 5) rend ce redéploiement sans interruption.

## 4. Outil CI/CD

Nous choisissons GitHub Actions, pour deux critères concrets. Le premier est l'intégration native au dépôt : le code est déjà hébergé sur GitHub, le pipeline se déclenche sur push et pull request sans aucune infrastructure tierce, et le fichier de workflow (`.github/workflows/ci.yml`) est versionné avec le code, ce qui sert directement le critère de reproductibilité de la grille. Le second critère est la gestion des secrets et de l'écosystème : les identifiants Docker Hub sont stockés dans les secrets chiffrés de GitHub et jamais en clair dans le repo (exigence explicite de la grille de notation), et les actions officielles (`actions/setup-python` avec cache pip, `docker/build-push-action`) permettent un pipeline court, lisible et rapide. Le pipeline exécutera les tests avec un seuil de couverture bloquant à 80 %, puis ne construira et ne poussera les images que si les tests passent.

## 5. Stratégie de déploiement

Nous retenons `RollingUpdate` avec `maxSurge: 1` et `maxUnavailable: 0` pour le service d'inférence, afin de garantir l'absence d'interruption de service pendant les mises à jour — y compris pendant la démonstration. Le point capital, appris à nos dépens lors de la séance 3, est que **la marge de surge doit être vérifiée sur les deux dimensions du quota, requests ET limits** : notre quota comptabilise les deux, et une première version du dimensionnement (limits plus généreuses, Σ limits.memory de 1344Mi) a produit un rollout bloqué — `exceeded quota: ... limits.memory=384Mi, used: 1344Mi, limited: 1536Mi` — alors que la marge des requests suffisait. Le nouveau pod ne pouvait pas être créé, et comme `maxUnavailable: 0` interdit de tuer l'ancien avant, la mise à jour restait figée sans que rien ne plante.

Le calcul corrigé, pour le pire cas (surge de l'inférence, le plus gros pod), est le suivant. Marge = quota − somme des valeurs permanentes :

- **requests** : CPU (2500 − 750) = 1750m ≥ 450m ✓ ; mémoire (1536 − 736) = 800Mi ≥ 448Mi ✓
- **limits** : CPU (2500 − 1300) = 1200m ≥ 700m ✓ ; mémoire (1536 − 960) = 576Mi ≥ 544Mi ✓

Les quatre inégalités tiennent, donc le nouveau pod peut démarrer avant l'arrêt de l'ancien sans violer le quota. Cette propriété a été validée expérimentalement par un `kubectl rollout restart deployment/inference` exécuté avec succès immédiatement après la correction. Les surges du preprocessing (200m / 192Mi de requests) et du monitoring (100m / 96Mi) tiennent a fortiori.

Un point de vigilance demeure : si un rollout de l'inférence coïncide avec l'exécution du CronJob de segmentation (limits 400m / 384Mi), la somme des limits.memory atteint 960 + 384 = 1344Mi et la marge restante (192Mi) ne suffit plus au surge de 544Mi. Ce risque est traité par exploitation plutôt que par sur-dimensionnement : le CronJob est planifié toutes les heures pour une exécution de quelques minutes, et les mises à jour sont des opérations manuelles rares que nous effectuerons hors de ces fenêtres ; le risque résiduel est un rollout temporairement en attente, sans interruption de service puisque `maxUnavailable: 0` conserve l'ancien pod actif. Un `LimitRange` complète le dispositif en imposant des valeurs par défaut (defaultRequest 100m / 128Mi, default 250m / 256Mi) et des bornes (min 50m / 64Mi, max 1000m / 768Mi) cohérentes avec le tableau de dimensionnement, afin qu'aucun conteneur ne puisse déclarer des ressources hors de l'enveloppe planifiée.
