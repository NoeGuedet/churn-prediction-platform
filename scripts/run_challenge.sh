#!/bin/bash
# Challenge de charge — séance 4.
# Exécute les 3 niveaux imposés (nominal 10, charge 50, stress 150 req/min,
# 5 min chacun) en relevant kubectl top pods toutes les 30 s, les métriques
# du monitoring avant/après, et l'état des pods (restarts) avant/après.
# Sorties : docs/captures/challenge_{nominal,charge,stress}.txt
set -u
cd "$(dirname "$0")/.."
NS=projet-noe
mkdir -p docs/captures

pkill -f "port-forward svc/inference-svc" 2>/dev/null
pkill -f "port-forward svc/monitoring-svc" 2>/dev/null
sleep 1
kubectl port-forward svc/inference-svc 8002:8002 -n $NS >/dev/null 2>&1 &
kubectl port-forward svc/monitoring-svc 8003:8003 -n $NS >/dev/null 2>&1 &
sleep 4

run_level () {
  local level=$1
  local out=docs/captures/challenge_${level}.txt
  echo "=== NIVEAU: $level — début $(date '+%H:%M:%S') ===" > "$out"
  echo "--- kubectl get pods (avant) ---" >> "$out"
  kubectl get pods -n $NS >> "$out" 2>&1
  echo "--- monitoring /metrics (avant) ---" >> "$out"
  curl -s http://localhost:8003/metrics >> "$out"
  echo >> "$out"

  # Échantillonnage kubectl top toutes les 30 s pendant le test (5 min).
  ( for i in $(seq 1 10); do
      sleep 30
      echo "--- kubectl top pods @ $(date '+%H:%M:%S') ---" >> "$out"
      kubectl top pods -n $NS >> "$out" 2>&1
    done ) &
  local sampler=$!

  .venv/bin/python scripts/load_test.py --case churn --level "$level" \
    --url http://localhost:8002/predict >> "$out" 2>&1
  wait $sampler 2>/dev/null

  echo "--- monitoring /metrics (après) ---" >> "$out"
  curl -s http://localhost:8003/metrics >> "$out"
  echo >> "$out"
  echo "--- kubectl get pods (après) ---" >> "$out"
  kubectl get pods -n $NS >> "$out" 2>&1
  echo "=== FIN $level — $(date '+%H:%M:%S') ===" >> "$out"
  echo "[challenge] niveau $level terminé -> $out"
}

run_level nominal
run_level charge
run_level stress
echo "CHALLENGE COMPLET"
