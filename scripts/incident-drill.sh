#!/usr/bin/env bash
# Incident drill: steady load + a "bad release" (payment gateway failing on /checkout) shipped via GitOps,
# then a rollback with git revert. Expected: PaymentApiAvailabilityBudgetBurnCritical fires, then resolves.
# Run it when the last hour had no other load test, otherwise the 1h window dilutes the error ratio.
#   ./scripts/incident-drill.sh
set -euo pipefail
cd "$(dirname "$0")/.."
VALUES=deploy/helm/payment-api/values.yaml
sync() { kubectl -n argocd annotate application payment-api argocd.argoproj.io/refresh=hard --overwrite >/dev/null; }
log() { echo "[$(date -u +%H:%M:%S)] $*"; }
# Prints "firing" when the critical availability alert is firing in Prometheus (port-forward on :9090).
critical_state() {
  curl -s localhost:9090/api/v1/alerts | python3 -c "import json,sys
alerts = json.load(sys.stdin)['data']['alerts']
print(next((a['state'] for a in alerts if a['labels']['alertname'] == 'PaymentApiAvailabilityBudgetBurnCritical'), 'inactive'))"
}

log "1/4 steady traffic: k6 'incident' scenario (120 VU, 12 min)"
SCENARIO=incident ./scripts/run-load-test.sh > /dev/null 2>&1 &
sleep 120

log "2/4 bad release: CHECKOUT_ERROR_RATE=1 (payment gateway down) pushed to main"
git pull -q --rebase
sed -i 's|  CHECKOUT_ERROR_RATE: .*|  CHECKOUT_ERROR_RATE: "1"|' "$VALUES"
git commit -qm "feat: switch /checkout to the new payment gateway client" "$VALUES"
git push -q
sync
BAD=$(git rev-parse --short HEAD)

log "3/4 waiting for the critical burn-rate alert"
until [ "$(critical_state)" = firing ]; do sleep 10; done
log "ALERT FIRING - on-call is paged (kubectl -n monitoring logs deploy/alert-sink)"
sleep 90

log "4/4 mitigation: git revert $BAD"
git revert --no-edit "$BAD" >/dev/null
git push -q
sync
until [ "$(critical_state)" != firing ]; do sleep 15; done
log "alert resolved"
wait
