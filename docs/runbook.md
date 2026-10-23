# Runbook - payment-api error budget burn

## PaymentApiAvailabilityBudgetBurnCritical (page)
The 5xx ratio is above 7.2 % (14.4 x 0.5 %) over both 1 h and 5 min: at this pace the 30-day error budget is gone in ~2 days.

1. Open the Grafana dashboard **Payment API - SRE**: which route returns 5xx? 503 = load shedding (overload), 500 = application error.
2. 503 (overload): `kubectl -n payment get hpa,pods`. Is the HPA at `maxReplicas`? Scale up
   (`kubectl -n payment scale deploy/payment-api --replicas=6`) or raise `MAX_IN_FLIGHT` / CPU limits.
3. 500: open the *Error logs* panel, click the `trace_id` -> trace in Tempo -> failing span.
4. Recent deployment? `argocd app history payment-api`, roll back with `argocd app rollback payment-api <id>`
   (or revert the GitOps commit).

## PaymentApiAvailabilityBudgetBurnWarning (Slack)
The 5xx ratio is above 3 % (6 x 0.5 %) over 6 h and 30 min. Not urgent, but the budget will be exhausted in ~5 days:
open a ticket, investigate during working hours, consider freezing risky releases.

## Latency alerts
Same logic on the share of requests slower than 200 ms (budget 5 %). Check p95 by route, CPU throttling
(`container_cpu_cfs_throttled_periods_total`) and the `/checkout` slow path.
