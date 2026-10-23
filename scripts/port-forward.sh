#!/usr/bin/env bash
# Opens the UIs on localhost. Ctrl+C stops everything.
#   Grafana      http://localhost:3000  (admin / admin)
#   Prometheus   http://localhost:9090
#   Alertmanager http://localhost:9093
#   ArgoCD       http://localhost:8081  (admin / see below)
#   payment-api  http://localhost:8080
set -u
kubectl -n monitoring port-forward svc/kps-grafana 3000:80 &
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090 &
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-alertmanager 9093:9093 &
kubectl -n argocd port-forward svc/argocd-server 8081:80 &
kubectl -n payment port-forward svc/payment-api 8080:80 &
echo "ArgoCD admin password: $(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d)"
trap 'kill $(jobs -p)' EXIT
wait
