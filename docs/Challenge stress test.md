# Challenge stress test : compétition de résilience 



Owner louis reynouard Tags Created time May 1, 2026 5o16 PM 

## Principe 

Après avoir validé les trois niveaux de charge imposés (nominal, charge, stress), chaque étudiant ou binôme peut tenter de pousser son système aussi loin que possible avec le mode `extreme` . L'objectif est double : trouver le point de rupture du système, et documenter comment il se comporte à ce point. 

Le stress test extrême est optionnel. Il n'est pas éliminatoire. Il donne lieu à un - bonus de 0 à 2 points sur la moyenne finale, attribué selon les critères détaillés ci dessous. 

## Règles du stress test extrême 

Le protocole est identique pour tous. Le script de charge est le même que pour les trois niveaux imposés. Seul le paramètre `--level extreme` change, et le `--rate` est libre. 

```
python scripts/load_test.py \
--case images \
--level extreme \
--rate300\
--url http://$(minikube service inference-svc -n projet-T
RIGRAMME --url |tail -1)/predict
```

Challenge stress test : compétition de résilience 

1 

Le rate est choisi par l'étudiant. Il est recommandé dʼaugmenter progressivement : 200, puis 300, puis 500, etc. Chaque palier est testé pendant 5 minutes. On note le dernier palier où le taux de réussites dépasse 80%. 

Le système doit repartir proprement. Après le test extrême, le système doit retrouver un état stable en moins de 2 minutes (tous les pods en état `Running` , aucun `CrashLoopBackOff` ). Un système qui nécessite un redémarrage complet du cluster pour revenir à la normale ne sera pas classé. 

Le quota ne change pas. Aucune modification des fichiers `quota.yaml` et `limitrange.yaml` nʼest permise entre les tests imposés et le stress test extrême. Les ʼ optimisations doivent s inscrire dans le même cadre de ressources. 

## Ce qui est évalué pour le bonus 

Le bonus nʼest pas attribué uniquement au meilleur débit. Il récompense également la qualité de lʼanalyse. 

|Critère|Bonus<br>maximum|
|---|---|
|Débit maximal soutenu avec taux de réussites> 80%|1point|
|Analyse du comportement au point de rupture(ce qui casse,pourquoi,<br>comment le système récupère)|1point|



Le critère de débit est classé par rang. Le premier groupe obtient 1 point. Les suivants obtiennent proportionnellement moins selon lʼécart avec le premier (un écart de moins de 10% donne le même score, un écart de plus de 50% donne 0.3 point). 

Lʼanalyse du comportement est notée indépendamment du classement. Un groupe classé dernier sur le débit mais qui documente précisément ce qui sʼest passé peut obtenir le point complet sur ce critère. 

## Le livrable du stress test extrême 

Un document Markdown `STRESS_TEST.md` à la racine du repo. Il contient : 

Challenge stress test : compétition de résilience 

2 

- Les résultats bruts. Pour chaque palier testé, un tableau avec : rate configuré, requêtes envoyées, requêtes réussies LHTTP 200M, latence moyenne, latence P95, nombre de pods restartés pendant le test. 

- Lʼidentification du point de rupture. Le palier auquel le taux de réussites passe sous 80% est le point de rupture. Ce palier est identifié et analysé : quel - 

- service a lâché en premier LOOMKill, throttling CPU, time out applicatif) ? La preuve vient de `kubectl describe pod` ou `kubectl logs` au moment du test. 

- La récupération. Une capture de `kubectl get pods` après 2 minutes montrant que le système est revenu à lʼétat stable. 

- Une proposition dʼamélioration. Si les ressources étaient doublées (quota de 10 Go au lieu de 5 Go), quel service bénéficierait le plus de ressources supplémentaires et pourquoi ? Ce raisonnement doit être basé sur les mesures produites, pas sur une intuition générale. 

Challenge stress test : compétition de résilience 

3 

