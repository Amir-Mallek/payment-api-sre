#!/usr/bin/env bash
# Runs the k6 test inside the cluster. Optional: SCENARIO=ramp_up|stress|spike (default: all three, ~14 min).
set -euo pipefail
cd "$(dirname "$0")/.."
NAME="k6-${SCENARIO:-full}-$(date +%H%M%S)"
kubectl create namespace loadtest --dry-run=client -o yaml | kubectl apply -f -
kubectl -n loadtest create configmap k6-script --from-file=k6/load-test.js --dry-run=client -o yaml | kubectl apply -f -
ARGS='"run", "--out", "experimental-prometheus-rw", "--tag", "testid=payment-api-load",'
[ -n "${SCENARIO:-}" ] && ARGS="$ARGS \"-e\", \"SCENARIO=$SCENARIO\","
sed -e "s|name: k6-load-test|name: $NAME|" \
    -e "s|args: \[.*\]|args: [$ARGS \"/scripts/load-test.js\"]|" k6/job.yaml | kubectl apply -f -
kubectl -n loadtest wait --for=condition=ready pod -l job-name="$NAME" --timeout=2m
kubectl -n loadtest logs -f "job/$NAME" | tee "k6/results/$NAME.txt"
