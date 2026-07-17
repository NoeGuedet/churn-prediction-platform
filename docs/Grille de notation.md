# Grilles de notation 



Owner louis reynouard Tags Created time May 1, 2026 5o14 PM 

## Principe général 

Le module donne lieu à deux notes distinctes, de poids égaux dans la moyenne finale. 

La note technique porte sur le livrable Git et son déploiement. Elle évalue ce qui a été construit, comment cela fonctionne sous contrainte, et la qualité des justifications écrites. 

La note orale porte sur la compréhension du système construit. Elle évalue la capacité de l'étudiant à expliquer ses propres décisions, à raisonner sur les mesures produites, et à anticiper l'effet de modifications du contexte. 

Pour les binômes, la note technique est commune. La note orale est individuelle. 

## Note 1 : Livrable technique (50% de la moyenne) 

### Critères éliminatoires 

Si l'un de ces critères n'est pas satisfait, une pénalité de 5 points est appliquée sur la note technique finale. 

Le repo se déploie sans modification manuelle depuis un `git clone` sur un environnement vierge. 

Le pipeline CI/CD échoue si les tests échouent. Un pipeline qui pousse une image Docker malgré des tests en échec est considéré non fonctionnel. 

### Grille de notation technique 

|Critère|Poids|0|2|4|6|8|10|
|---|---|---|---|---|---|---|---|
|Reproductibilité|30%|Impossible à<br>déployer|Démarre après<br>interventions<br>manuelles non<br>documentées|README<br>présent mais<br>incomplet,au<br>moins une<br>étape<br>manquante|Se déploie en<br>suivant le<br>README avec<br>une ou deux<br>corrections<br>mineures|Déploiement<br>fonctionnel en<br>une<br>commande,<br>README<br>complet|Déploiement<br>une comman<br>< 10min,<br>README<br>exhaustif,<br>aucune<br>intervention|
|Pipeline CI/CD|25%|Absent ou ne<br>se déclenche<br>pas|Se déclenche<br>mais ne bloque<br>jamais|Bloque sur les<br>tests mais<br>couverture<<br>80%|Tests bloquants<br>à80%,build<br>conditionnel,<br>secrets absents<br>ou en clair|Tests<br>bloquants,<br>couverture ≥<br>80%,secrets<br>gérés|Tests<br>bloquants,<br>couverture ≥<br>80%,secrets<br>gérés,pipelin<br>commenté et<br>maintenable|
|Respect du<br>quota|25%|Quota dépassé|Quota<br>respecté,<br>valeurs copiées<br>d'un exemple<br>sans mesure|Valeurs<br>estimées sans<br>`kubectl top` ,<br>marge non<br>calculée|Valeurs issues<br>de<br>`kubectl`<br>`top` mais<br>capture<br>absente du<br>livrable|Valeurs<br>mesurées avec<br>capture,marge<br>calculée|Valeurs<br>mesurées+<br>capture+<br>calcul du sur<br>RollingUpdat<br>+justification<br>de la stratégi<br>de déploieme|



Grilles de notation 

1 

|Critère|Poids|0|2|4|6|8|10|
|---|---|---|---|---|---|---|---|
|Challenge de<br>charge|20%|Aucune mesure<br>produite|Mesures pour<br>un seul niveau|Tableau pour<br>les trois<br>niveaux,pas de<br>correction|Tableau<br>complet+<br>correction<br>appliquée non<br>mesurée|Correction<br>appliquée et<br>mesurée<br>avant/après|Correction<br>justifiée par l<br>mesures,<br>analyse du<br>comporteme<br>mécanique,<br>conclusion su<br>le point de<br>rupture|



### Calcul de la note technique 

```
Note technique =(Reproductibilité × 0.30)
+(CI/CD × 0.25)
+(Quota × 0.25)
+(Challenge × 0.20)
```

La note obtenue est ramenée sur 20. 

## Note 2 : Défense orale (50% de la moyenne) 

### Format 

L'oral de soutenance dure 15 minutes et se déroule en trois parties. 

#### Partie 1 _ Présentation de la solution L5]7 minutes). 

Vous présentez votre architecture complète : les services, les modèles, les choix techniques majeurs et leurs justifications. Vous expliquez comment la contrainte de ressources a influencé vos décisions. Support visuel attendu (diagramme d'architecture, tableau de dimensionnement). 

#### Partie 2 _ Démo live L5]7 minutes). 

Vous montrez le système déployé et fonctionnel : les pods en état Running, une requête d'inférence en direct, les métriques du service de monitoring. Si le système ne démarre pas depuis votre commande, la démo est échouée. 

#### Partie 3 _ Questions L3]5 minutes). 

Questions sur les décisions prises, les résultats observés pendant le challenge de charge, et la cohérence entre l'Architecture Decision Record et le système produit. Les questions ne sont pas communiquées à l'avance. 

### Catégories de questions 

Catégorie A : les valeurs choisies. `requests` , `limits` , répartition du quota, stratégie de déploiement. Exemples : "Pourquoi 800Mi pour l'inférence et pas 1Gi ?", "Que se serait-il passé avec un RollingUpdate sur votre configuration ?", "Si je réduis votre quota de 20%, quel service ajustez-vous en premier ?" 

Catégorie B : les résultats du challenge de charge. Ce qui a été observé, la correction apportée. Exemples : "Votre P95 est à 4.2s au niveau stress. Qu'est-ce qui l'explique ?", "Votre correction a réduit la latence de 30%. Expliquez mécaniquement pourquoi.", "Que feriez-vous différemment ?" 

Catégorie C : les décisions de l'Architecture Decision Record. Exemples : "Vous avez choisi TF]IDF plutôt que DistilBERT. Dans quel contexte ce choix serait-il inversé ?", "Votre deuxième modèle est dans le même service que le premier. Quel problème cela crée-t-il si l'un est mis à jour indépendamment ?" 

### Grille de notation orale 

Grilles de notation 

2 

|Critère|Poids|0|2|4|6|8|10|
|---|---|---|---|---|---|---|---|
|Catégorie A:<br>justification des<br>valeurs de<br>ressources|35%|Incapacité à<br>expliquer les<br>valeurs|Explication<br>vague,aucun<br>chiffre|Explication<br>générale sans<br>lien avec les<br>mesures réelles|Chiffres cités<br>mais sans<br>raisonnement<br>sur les marges|Chiffres de<br>`kubectl top`<br>cités,marge<br>calculée|Chiffres+<br>calcul de<br>marge+<br>capacité à<br>raisonner sur<br>une<br>modification d<br>quota|
||||||||Explication|
|Catégorie B:<br>compréhension<br>du<br>comportement<br>sous charge|35%|Pas de<br>mesures ou<br>incapacité à les<br>présenter|Résultats<br>présentés sans<br>aucune analyse|Description des<br>résultats,<br>causes non<br>identifiées|Causes<br>identifiées,<br>correction non<br>expliquée<br>mécaniquement|Explication<br>mécanique du<br>comportement<br>+justification<br>de la correction|mécanique+<br>justification+<br>proposition<br>d'une<br>optimisation<br>alternative<br>argumentée|
||||||||Trade-offs<br>reconnus+|
|Catégorie C:<br>défense de<br>l'Architecture<br>Decision<br>Record|30%|ADR non<br>réalisé ou<br>impossible à<br>défendre|Choix rappelés<br>sans aucun<br>argument|Arguments<br>présents mais<br>génériques,<br>non liés au<br>contexte|Arguments liés<br>au contexte,<br>trade-offs<br>partiellement<br>reconnus|Trade-offs<br>reconnus et<br>argumentés|capacité à<br>raisonner sur<br>des variantes<br>du contexte<br>(quota réduit,<br>autre modèle<br>autre stratégi|



### Calcul de la note orale 

```
Note orale =(Catégorie A × 0.35)
+(Catégorie B × 0.35)
+(Catégorie C × 0.30)
```

La note obtenue est ramenée sur 20. 

## Bonus : stress test extrême (0 à 2 points) 

Optionnel. Ne pénalise pas les groupes qui ne le tentent pas. Plafonne à 20/20. 

Débit maximal soutenu L1 point). Classement sur le nombre de requêtes HTTP 200 en 5 minutes au niveau `extreme` . Le premier groupe obtient 1 point. Écart < 10% o 1 point. Écart entre 10% et 50% : entre 0.3 et 0.9 point. Écart > 50% o 0.3 point. 

Qualité de l'analyse du point de rupture L1 point). Indépendant du classement. Évalué sur `STRESS_TEST.md` : identification ' précise du service qui a lâché, preuve via les logs ou `kubectl describe` , proposition d amélioration basée sur les mesures. 

Grilles de notation 

3 

