#!/bin/bash
# Load challenge — session 4.
# Runs the 3 required levels (nominal 10, charge 50, stress 150 req/min,
# 5 min each) while recording kubectl top pods every 30 s, monitoring
# metrics before/after, and pod status (restarts) before/after.
# Outputs: docs/captures/challenge_{nominal,charge,stress}.txt
set -u
cd "$(dirname "$0")/.."
NS=churn-prediction-platform
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
  echo "=== LEVEL: $level — start $(date '+%H:%M:%S') ===" > "$out"
  echo "--- kubectl get pods (before) ---" >> "$out"
  kubectl get pods -n $NS >> "$out" 2>&1
  echo "--- monitoring /metrics (before) ---" >> "$out"
  curl -s http://localhost:8003/metrics >> "$out"
  echo >> "$out"

  # Sample kubectl top every 30 s during the test (5 min).
  ( for i in $(seq 1 10); do
      sleep 30
      echo "--- kubectl top pods @ $(date '+%H:%M:%S') ---" >> "$out"
      kubectl top pods -n $NS >> "$out" 2>&1
    done ) &
  local sampler=$!

  .venv/bin/python scripts/load_test.py --level "$level" \
    --url http://localhost:8002/predict >> "$out" 2>&1
  wait $sampler 2>/dev/null

  echo "--- monitoring /metrics (after) ---" >> "$out"
  curl -s http://localhost:8003/metrics >> "$out"
  echo >> "$out"
  echo "--- kubectl get pods (after) ---" >> "$out"
  kubectl get pods -n $NS >> "$out" 2>&1
  echo "=== END $level — $(date '+%H:%M:%S') ===" >> "$out"
  echo "[challenge] level $level done -> $out"
}

run_level nominal
run_level charge
run_level stress
echo "CHALLENGE COMPLETE"
