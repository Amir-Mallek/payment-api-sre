# Guide de présentation (~15 min + questions)

## Avant la présentation (30 min avant)

```bash
minikube start -p tp2                       # le cluster existe déjà, ~1 min
kubectl get pods -A | grep -v Running       # tout doit être Running
cd ~/kraya/devops/tp2 && ./scripts/port-forward.sh   # laisser tourner dans un terminal
```

Onglets à ouvrir dans le navigateur :
1. https://github.com/Amir-Mallek/payment-api-sre (README avec le schéma)
2. https://github.com/Amir-Mallek/payment-api-sre/pull/1 (PR bloquée)
3. https://github.com/Amir-Mallek/payment-api-sre/actions (pipeline vert sur main)
4. http://localhost:8081 ArgoCD (admin / mot de passe affiché par port-forward.sh)
5. http://localhost:3000/d/payment-api-sre Grafana (admin / admin), plage "Last 6 hours"
6. http://localhost:9090/alerts Prometheus, http://localhost:9093 Alertmanager
7. `docs/RAPPORT-SRE.md` sur GitHub (captures de secours si une démo plante)

Terminal prêt avec une police lisible (Ctrl + pour zoomer).

---

## Déroulé

### 1. Introduction (1 min) - onglet README

> "Notre objectif : livrer un microservice de paiement en continu, mais avec des barrières de qualité et de
> sécurité à chaque étape, puis prouver par la mesure qu'il tient ses objectifs de service. J'ai construit
> la chaîne complète : du commit jusqu'à l'alerte d'astreinte."

Montrer le schéma d'architecture du README, de gauche à droite : GitHub Actions, GHCR, ArgoCD, Gatekeeper,
le service, puis la stack d'observabilité.

### 2. Le microservice (1 min 30) - `app/main.py`

> "C'est une API FastAPI : catalogue, paiement avec validation de carte par l'algorithme de Luhn, un endpoint
> `/checkout` volontairement lent et un endpoint `/flaky` qui renvoie des 500 de façon aléatoire. Le service
> expose `/metrics` au format Prometheus via le SDK OpenTelemetry. J'ai choisi moi-même les bornes de
> l'histogramme de latence pour qu'il y en ait une à exactement 200 ms : c'est le seuil du SLO, donc le SLI
> est un ratio exact, pas une estimation."

Point fort à dire : *"Chaque pod fait du load shedding : au-delà de 60 requêtes simultanées il répond 503
avec Retry-After. C'est un vrai pattern SRE : sacrifier quelques requêtes pour protéger la latence de toutes
les autres."*

Option démo (10 s) : `curl -s localhost:8080/metrics | grep http_server_requests_total | head`

### 3. Tests et couverture (1 min) - terminal

```bash
source .venv/bin/activate && pytest -q
```

> "45 tests, cas nominaux et cas limites : carte invalide, rupture de stock, quantité 0 et 101, devise
> inconnue, route inconnue. Couverture 100 %, rapports Cobertura et LCOV. Pytest échoue tout seul sous
> 85 % grâce à `--cov-fail-under=85` : c'est la première barrière."

### 4. Quality Gate SonarQube (2 min) - onglet PR #1

> "Pour le prouver, j'ai ouvert une PR non conforme : un module d'export sans tests, avec MD5, un générateur
> pseudo-aléatoire pour un jeton, `subprocess` avec `shell=True`, et trois fonctions copiées-collées."

Cliquer sur **Details** du check *SonarQube analysis & Quality Gate*, ou montrer la capture
`04-sonarqube-quality-gate-failed.png`.

> "La Quality Gate échoue sur exactement les trois critères demandés : 0 % des security hotspots revus,
> 16 % de duplication pour 3 % autorisés, couverture sous 85 %. Résultat : le build, le scan Trivy, le push
> et le déploiement sont *skipped*. Le code n'atteint jamais le cluster."

Détail technique à mentionner : *"SonarQube tourne comme service container dans le job, et un script le
configure par l'API (profil, gate, token). Pas de compte externe, et la configuration est versionnée dans
le dépôt. J'ai choisi la version 25.1 parce que la 26 ne classe plus les hotspots Python comme hotspots."*

### 5. Pipeline complet (1 min) - onglet Actions, run vert sur main

> "Sur main : lint et tests, SonarQube, build Docker, Trivy qui échoue sur toute vulnérabilité CRITICAL,
> push sur GHCR avec le SHA du commit comme tag, puis un job GitOps qui commit le nouveau tag dans le
> `values.yaml` du chart Helm. La CI ne touche jamais au cluster, c'est ArgoCD qui tire les changements."

En parallèle : *"un job teste aussi les politiques Rego avec `gator` et vérifie que le chart rendu est conforme
avant de builder."*

### 6. OPA Gatekeeper (2 min) - terminal + ArgoCD

```bash
kubectl apply -f policies/tests/bad-latest-tag.yaml
kubectl apply -f policies/tests/bad-no-resources.yaml
kubectl apply -f policies/tests/good-deployment.yaml --dry-run=server
```

> "Deux ConstraintTemplates en Rego. La première refuse le tag latest, y compris le latest implicite d'une
> image sans tag. La seconde exige requests et limits CPU et mémoire sur chaque conteneur. Le refus vient de
> l'API Server lui-même, via le webhook d'admission : même un `kubectl` admin est bloqué."

Puis dans ArgoCD, ouvrir l'application `noncompliant-demo` : **Sync Failed** avec le message Gatekeeper.

> "Même chose via GitOps : un manifeste non conforme poussé dans Git est refusé à la synchronisation.
> L'application `payment-api`, elle, est Synced et Healthy."

### 7. Observabilité (2 min) - Grafana Explore

> "Les trois signaux : métriques scrappées par Prometheus grâce aux annotations du pod, logs JSON collectés
> par Alloy vers Loki, traces OTLP envoyées au Collector OpenTelemetry puis à Tempo."

Démo : Explore -> Loki -> `{app="payment-api", level="ERROR"}` -> ouvrir une ligne -> bouton
**View trace in Tempo** -> la trace s'ouvre à côté.

> "Chaque ligne de log contient le trace_id du span courant. En un clic on passe du log à la trace, et
> depuis la trace on revient aux logs."

Anecdote à raconter : *"Pendant le spike à 1500 VU, Tempo a saturé sa limite d'ingestion et a crashé. J'ai
ajouté du tail sampling dans le Collector : on garde 100 % des traces en erreur et des traces lentes, et
10 % des autres. C'est ce qu'on fait en production."*

### 8. SLO, Error Budget, dashboard (2 min) - Grafana dashboard

> "Deux SLO : 99,5 % de requêtes sans 5xx, et 95 % des requêtes sous 200 ms. Sur 30 jours, le budget de
> disponibilité représente 0,5 % des requêtes, l'équivalent de 3 h 36 d'indisponibilité totale."

Parcourir le dashboard de haut en bas : jauges d'Error Budget restant (calculées sur la période affichée),
Rate, Errors, Duration (p50 à p99 avec la ligne des 200 ms), Burn rate.

### 9. Test de charge et incident (2 min 30) - dashboard sur la plage du test

> "Le script k6 enchaîne trois scénarios : montée à 100 VU, stress prolongé à 500 VU, puis un spike à
> 1500 VU pendant 30 secondes. Il tourne dans le cluster pour ne pas être limité par un port-forward."

Résultats à citer :
- ramp-up et stress : dans les SLO (p95 125 ms, 0,3 % d'erreurs), l'HPA est passé de 2 à 6 pods ;
- spike : 1 365 req/s, SLO de disponibilité violé (0,54 % côté serveur, 1,1 % côté k6), p95 client 287 ms ;
- *"Le serveur voit moins d'erreurs que le client : 240 requêtes ont échoué avant d'atteindre l'application.
  Un SLI côté serveur seul est optimiste."*

> "Le spike n'a pas déclenché d'alerte, et c'est voulu. Sur une heure, 30 secondes de pic pèsent peu :
> on ne réveille pas l'astreinte pour ça. Pour montrer l'alerte, j'ai simulé un vrai incident : une
> mauvaise release, déployée par GitOps, qui casse la passerelle de paiement."

Montrer la capture de l'incident (`17-...`, `13-prometheus-alerts-firing.png`, `14-alertmanager-alerts.png`) :
burn rate au-dessus de 14,4 sur 5 min et sur 1 h, alerte Critical *Firing*, page reçue par le receiver,
puis `git revert` et retour à la normale.

### 10. Alerting multi-window multi-burn-rate (1 min)

> "Burn rate 14,4 sur 1 heure, c'est 2 % du budget mensuel brûlé en une heure : à ce rythme le budget est
> épuisé en deux jours, donc on appelle l'astreinte. Burn rate 6 sur 6 heures, c'est 5 % du budget : on
> prévient sur Slack. Chaque alerte combine une fenêtre longue, pour la significativité, et une fenêtre
> courte, pour que l'alerte retombe vite après la correction. Quand le critical est actif, une règle
> d'inhibition coupe le warning du même SLO pour éviter le bruit."

### 11. Conclusion (30 s)

> "Bilan : aucune ligne de code n'atteint la production sans passer les tests, la Quality Gate, Trivy et
> Gatekeeper, et une fois en production on mesure ce que vivent les utilisateurs. La prochaine étape serait
> d'autoscaler sur le nombre de requêtes plutôt que sur le CPU, l'HPA CPU s'étant montré trop lent pour le spike."

---

## Questions probables et réponses

**Pourquoi poser les conditions SonarQube sur le code global et pas seulement sur le new code ?**
L'instance est éphémère : chaque analyse est une première analyse, et SonarQube n'évalue pas le new code
d'une première analyse. Les conditions globales garantissent un échec quand même. Avec une instance
permanente, les conditions new code suffiraient.

**Pourquoi ne pas utiliser SonarCloud ?**
SonarCloud demande un compte, un token, et ne permet pas toujours une Quality Gate personnalisée selon le plan.
Ici la gate est définie par le script, versionnée et reproductible, sans aucun secret.

**Pourquoi Gatekeeper ET gator dans la CI ?**
Gatekeeper est la barrière obligatoire, côté cluster. Gator donne un retour plus tôt, dès la PR
(shift left), et teste les règles Rego comme du code.

**Pourquoi exclure des namespaces ?**
Les charts tiers (monitoring, ArgoCD) ne définissent pas tous leurs resources. En production, on les
corrigerait par des values plutôt que de les exclure.

**Que se passe-t-il si Trivy trouve une CVE CRITICAL ?**
Le job sort en code 1, rien n'est poussé ni déployé. `--ignore-unfixed` évite de bloquer sur des CVE sans
correctif disponible. Les HIGH sont publiés en artefact, sans bloquer.

**Pourquoi 14,4 et 6 ?**
Budget mensuel = 720 h. Brûler 2 % en 1 h donne 0,02 × 720 / 1 = 14,4. Brûler 5 % en 6 h donne
0,05 × 720 / 6 = 6. (Google SRE Workbook, chapitre "Alerting on SLOs".)

**Comment est calculé le p95 ?**
`histogram_quantile(0.95, ...)` interpole dans l'histogramme. Le SLO lui-même est mesuré sans
interpolation : c'est la part de requêtes dans le bucket `le="0.2"`.

**Pourquoi le dashboard montre-t-il un budget 30 jours à -8000 % ?**
Le cluster n'a que quelques heures d'historique, et un test brutal (40 % d'erreurs) y pèse énormément.
La jauge principale calcule le budget sur la période affichée.

**Les logs : pourquoi Alloy et pas Promtail ?**
Promtail est déprécié au profit d'Alloy. Alloy lit les logs via l'API Kubernetes, ce qui fonctionne quel
que soit le runtime (Docker sur minikube, containerd sur k3s).

## Si une démo plante
Toutes les preuves sont dans `docs/screenshots/` et `docs/evidence/`, et le rapport `docs/RAPPORT-SRE.md`
les intègre. Basculer sur le rapport et continuer.
