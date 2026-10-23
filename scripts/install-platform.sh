#!/usr/bin/env bash
# Installs the platform on the current kube context: Gatekeeper + policies, observability stack, ArgoCD.
# Usage: SLACK_WEBHOOK_URL=https://hooks.slack.com/services/... ./scripts/install-platform.sh
set -euo pipefail
cd "$(dirname "$0")/.."

helm repo add gatekeeper https://open-policy-agent.github.io/gatekeeper/charts
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
helm repo add argo https://argoproj.github.io/argo-helm
helm repo update

echo "==> OPA Gatekeeper"
helm upgrade --install gatekeeper gatekeeper/gatekeeper --version 3.23.1 \
  -n gatekeeper-system --create-namespace --set replicas=1 --wait
kubectl apply -f policies/templates/
until kubectl get crd k8sdisallowlatesttag.constraints.gatekeeper.sh k8srequiredresources.constraints.gatekeeper.sh >/dev/null 2>&1; do sleep 2; done
kubectl apply -f policies/constraints/

echo "==> Observability (monitoring namespace)"
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
kubectl -n monitoring create secret generic alertmanager-slack \
  --from-literal=url="${SLACK_WEBHOOK_URL:-https://hooks.slack.com/services/T000/B000/XXXX}" \
  --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install kps prometheus-community/kube-prometheus-stack --version 92.11.0 \
  -n monitoring -f observability/kube-prometheus-stack-values.yaml --wait --timeout 10m
helm upgrade --install loki grafana/loki --version 7.5.0 -n monitoring -f observability/loki-values.yaml --wait --timeout 10m
helm upgrade --install tempo grafana/tempo --version 1.24.4 -n monitoring -f observability/tempo-values.yaml --wait
helm upgrade --install otel-collector open-telemetry/opentelemetry-collector --version 0.177.0 \
  -n monitoring -f observability/otel-collector-values.yaml --wait
helm upgrade --install alloy grafana/alloy --version 1.14.2 -n monitoring -f observability/alloy-values.yaml --wait
kubectl apply -f observability/alert-sink.yaml
kubectl apply -f observability/rules/
kubectl -n monitoring create configmap payment-api-dashboard \
  --from-file=observability/dashboards/payment-api-sre.json --dry-run=client -o yaml \
  | kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -

echo "==> ArgoCD"
helm upgrade --install argocd argo/argo-cd --version 10.10.5 -n argocd --create-namespace \
  -f deploy/argocd/argocd-values.yaml --wait --timeout 10m
kubectl apply -f deploy/argocd/application.yaml

echo "Done. Run ./scripts/port-forward.sh to open Grafana, Prometheus, Alertmanager and ArgoCD."
