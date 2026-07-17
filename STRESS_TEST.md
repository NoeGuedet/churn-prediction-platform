# Stress test extrême — compétition de résilience

Cas 3 (churn télécom), namespace `projet-noe`. Protocole : `scripts/load_test.py --case churn --level extreme --rate N --duration 300`, paliers croissants de 5 minutes, quota et limitrange **inchangés** par rapport aux tests imposés. Captures brutes : `docs/captures/extreme.txt` (paliers 200→1500) et `docs/captures/extreme2.txt` (paliers 2000→3000).

## 1. Résultats bruts

| Palier (req/min) | Envoyées | Réussies (HTTP 200) | Taux | Latence moy | Latence P95 | Restarts pods |
|---|---|---|---|---|---|---|
| 200 | 990 | 990 | 100 % | 24 ms | 30 ms | 0 |
| 300 | 1477 | 1477 | 100 % | 23 ms | 29 ms | 0 |
| 500 | 2435 | 2435 | 100 % | 22 ms | 29 ms | 0 |
| 700 | 3375 | 3375 | 100 % | 19 ms | 27 ms | 0 |
| 900 | 4285 | 4285 | 100 % | 16 ms | 22 ms | 0 |
| 1200 | 5605 | 5605 | 100 % | 14 ms | 18 ms | 0 |
| 1500 | 6878 | 6878 | 100 % | 13 ms | 16 ms | 0 |
| 2000 | 8903 | 8903 | 100 % | 12 ms | 15 ms | 0 |
| 2500 | 10834 | 10834 | 100 % | 11 ms | 14 ms | 0 |
| **3000** | **12638** | **12638** | **100 %** | **10 ms** | **13 ms** | **0** |

**Débit maximal soutenu : 12 638 requêtes HTTP 200 en 5 minutes (3000 req/min configurés, ~42 req/s effectives), avec 0 restart et 0 OOMKill.** Aucun palier n'est passé sous 80 % : le point de rupture du système n'a pas été atteint dans les limites du protocole.

## 2. Identification du point de rupture (non atteint — analyse du plafond mesuré)

Le système n'a pas cassé : l'analyse porte donc sur ce qui a réellement limité le test, et sur une projection fondée sur les mesures pour identifier ce qui casserait en premier.

**Ce qui a limité le test : le côté client, pas le cluster.** Preuves chiffrées :

- Au palier 3000, **12 638 requêtes effectives pour 15 000 configurées (84 %)** : le générateur (pool de 40 threads, une nouvelle connexion TCP par requête) ne parvient plus à émettre au rythme demandé, alors que les pods sont loin de leurs limites.
- La **latence diminue** quand le débit monte (24 ms → 10 ms) : à faible débit, chaque requête paie le coût d'établissement d'une connexion à travers le tunnel `kubectl port-forward` (proxy websocket via l'API server) et la couche réseau de Docker Desktop sur macOS ; à fort débit ce coût est amorti. Côté serveur (monitoring), la latence est ~6 ms contre 10-24 ms côté client : l'écart est du transport, pas de l'application.
- Ressources au palier maximal : inference **118m CPU pour 700m** de limit (17 %), mémoire **258Mi pour 544Mi**, preprocessing 28m/400m, monitoring 25m/200m. Aucune saturation, aucun restart.

Ces limites sont **spécifiques au banc d'essai** (macOS + Docker Desktop + port-forward + 40 threads) : dans une industrialisation propre (accès direct NodePort/Ingress sans tunnel, réseau Linux natif, connexions keep-alive), elles disparaissent.

**Projection : ce qui casserait en premier.** En extrapolant la pente mesurée (~5m CPU d'inference par tranche de 100 req/min effectifs aux paliers hauts), l'inference atteindrait sa `limits.cpu` de 700m autour de **14 000 req/min** — soit ~5× au-delà du plafond du générateur. Le premier mode d'échec serait le **throttling CPU** de l'inference (dégradation silencieuse du P95, sans crash — CPU compressible), pas un OOMKill : la mémoire est stable sur toute la plage (stockage borné du monitoring, aucune allocation persistante par requête).

## 3. Récupération

Aucune dégradation à récupérer : 0 restart, 0 OOMKill, 0 CrashLoopBackOff sur les 10 paliers. État stable confirmé immédiatement après le dernier palier (exigence « stable en moins de 2 minutes » largement satisfaite) :

### Capture récupération — kubectl get pods (système stable, 15:14:05)

```
NAME                             READY   STATUS      RESTARTS   AGE
inference-dcf79545d-bdz2p        1/1     Running     0          103m
monitoring-6dcbc9797-s4p72       1/1     Running     0          103m
preprocessing-7c7dc7549d-2rdzb   1/1     Running     0          54m
segmentation-29738227-h6vjx      0/1     Completed   0          7m5s
```

## 4. Proposition d'amélioration (si le quota était doublé, 1.5Gi → 3Gi)

Raisonnement fondé sur les mesures, pas sur l'intuition. La **seule métrique qui croît avec la charge** est le CPU de l'inference (8m au repos → 118m à 3000 req/min) ; la mémoire est plate partout, le preprocessing et le monitoring restent sous 30m. Doubler le quota devrait donc servir l'inference, pas la mémoire :

- **2 replicas de l'inference** (requests 450m/448Mi chacun) : répartition de la charge sur deux pods, lissage du P95 aux hauts débits, et tolérance au restart d'un pod pendant un pic. Coût : +450m/+448Mi de requests — indolore dans 3Gi, et le surge reste calculable (Σ requests 1200m/1184Mi, Σ limits 2240m/1504Mi, marge suffisante pour `maxSurge: 1`).
- **limits.cpu de l'inference à 1000m** par replica : recule le point de throttling projeté de ~14 000 à ~28 000 req/min effectifs au total.
- Rien pour le preprocessing (28m au max pour 400m) ni pour le monitoring (borné par construction) : y ajouter des ressources serait du gaspillage de quota, contraire à la discipline du TP.
