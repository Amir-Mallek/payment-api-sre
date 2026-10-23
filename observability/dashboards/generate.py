"""Generates payment-api-sre.json (Grafana dashboard: RED method, SLOs, error budget, burn rate)."""

import json
from pathlib import Path

SEL = 'namespace="payment", app_name="payment-api"'
BUCKETS = f"http_server_request_duration_seconds_bucket{{{SEL}}}"
PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
panels = []
_id = 0


def panel(kind, title, grid, targets, unit=None, desc="", **extra):
    global _id
    _id += 1
    p = {
        "id": _id,
        "type": kind,
        "title": title,
        "description": desc,
        "gridPos": dict(zip("xywh", grid, strict=True)),
        "datasource": PROM,
        "targets": [
            {"refId": chr(65 + i), "expr": expr, "legendFormat": legend, "datasource": PROM}
            for i, (expr, legend) in enumerate(targets)
        ],
        "fieldConfig": {"defaults": {}, "overrides": []},
        "options": {},
    }
    if unit:
        p["fieldConfig"]["defaults"]["unit"] = unit
    for key, value in extra.items():
        if key == "defaults":
            p["fieldConfig"]["defaults"].update(value)
        else:
            p[key] = value
    panels.append(p)
    return p


def row(title, y):
    global _id
    _id += 1
    panels.append(
        {
            "id": _id,
            "type": "row",
            "title": title,
            "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
            "panels": [],
        }
    )


def thresholds(*steps):
    return {"thresholds": {"mode": "absolute", "steps": [{"color": c, "value": v} for v, c in steps]}}


total = f"sum(increase(http_server_requests_total{{{SEL}}}[$__range]))"
errors = f'sum(increase(http_server_requests_total{{{SEL}, status_code=~"5.."}}[$__range]))'
fast = f'sum(increase(http_server_request_duration_seconds_bucket{{{SEL}, le="0.2"}}[$__range]))'
count = f"sum(increase(http_server_request_duration_seconds_count{{{SEL}}}[$__range]))"

row("SLO overview (over the selected time range)", 0)
panel(
    "stat",
    "Availability SLI",
    (0, 1, 4, 5),
    [(f"1 - ({errors} / {total})", "")],
    "percentunit",
    "Share of requests with HTTP status < 500. Objective: 99.5%.",
    defaults={"decimals": 3, **thresholds((None, "red"), (0.995, "green"))},
)
panel(
    "gauge",
    "Error budget remaining - availability",
    (4, 1, 5, 5),
    [(f"1 - (({errors} / {total}) / (1 - 0.995))", "")],
    "percentunit",
    "Dynamic: 1 - (observed error ratio / allowed error ratio 0.5%) over the dashboard time range.",
    defaults={
        "min": 0,
        "max": 1,
        "decimals": 1,
        **thresholds((None, "red"), (0.25, "orange"), (0.5, "green")),
    },
)
panel(
    "stat",
    "Latency SLI (< 200 ms)",
    (9, 1, 4, 5),
    [(f"{fast} / {count}", "")],
    "percentunit",
    "Share of requests served in less than 200 ms. Objective: 95%.",
    defaults={"decimals": 2, **thresholds((None, "red"), (0.95, "green"))},
)
panel(
    "gauge",
    "Error budget remaining - latency",
    (13, 1, 5, 5),
    [(f"1 - ((1 - {fast} / {count}) / (1 - 0.95))", "")],
    "percentunit",
    "1 - (share of slow requests / allowed 5%) over the dashboard time range.",
    defaults={
        "min": 0,
        "max": 1,
        "decimals": 1,
        **thresholds((None, "red"), (0.25, "orange"), (0.5, "green")),
    },
)
panel(
    "stat",
    "Burn rate (1h)",
    (18, 1, 3, 5),
    [
        ('slo:burn_rate:1h{slo="availability"}', "availability"),
        ('slo:burn_rate:1h{slo="latency"}', "latency"),
    ],
    "x",
    "Speed of error budget consumption. 1 = budget lasts exactly 30 days. Page at 14.4, Slack at 6.",
    defaults={"decimals": 1, **thresholds((None, "green"), (6, "orange"), (14.4, "red"))},
)
panel(
    "stat",
    "Firing SLO alerts",
    (21, 1, 3, 5),
    [('count(ALERTS{alertstate="firing", service="payment-api"}) or vector(0)', "")],
    None,
    defaults=thresholds((None, "green"), (1, "red")),
)

row("Rate", 6)
panel(
    "timeseries",
    "Requests per second by route",
    (0, 7, 16, 8),
    [(f"sum by (route) (rate(http_server_requests_total{{{SEL}}}[1m]))", "{{route}}")],
    "reqps",
    defaults={"custom": {"stacking": {"mode": "normal"}, "fillOpacity": 20}},
)
panel(
    "stat",
    "Total RPS",
    (16, 7, 4, 8),
    [(f"sum(rate(http_server_requests_total{{{SEL}}}[1m]))", "")],
    "reqps",
    options={"graphMode": "area"},
)
panel(
    "timeseries",
    "In-flight requests per pod",
    (20, 7, 4, 8),
    [(f"sum by (pod) (http_server_active_requests{{{SEL}}})", "{{pod}}")],
    None,
)

row("Errors", 15)
panel(
    "timeseries",
    "Errors per second by status code",
    (0, 16, 12, 8),
    [
        (
            f'sum by (status_code) (rate(http_server_requests_total{{{SEL}, status_code=~"5.."}}[1m]))',
            "HTTP {{status_code}}",
        )
    ],
    "reqps",
    defaults={"color": {"mode": "palette-classic"}},
)
panel(
    "timeseries",
    "Global error percentage",
    (12, 16, 12, 8),
    [
        (
            f'sum(rate(http_server_requests_total{{{SEL}, status_code=~"5.."}}[1m])) / '
            f"sum(rate(http_server_requests_total{{{SEL}}}[1m]))",
            "5xx ratio (1m)",
        ),
        ('slo:sli_error:ratio_rate5m{slo="availability"}', "5xx ratio (5m)"),
    ],
    "percentunit",
    defaults={
        "custom": {"thresholdsStyle": {"mode": "line"}},
        **thresholds((None, "transparent"), (0.005, "red")),
    },
)

row("Duration", 24)
lat = []
for q in ("0.50", "0.90", "0.95", "0.99"):
    lat.append(
        (
            f"histogram_quantile({q}, sum by (le) (rate({BUCKETS}[1m])))",
            f"p{int(float(q) * 100)}",
        )
    )
panel(
    "timeseries",
    "Latency distribution (p50 / p90 / p95 / p99)",
    (0, 25, 16, 8),
    lat,
    "s",
    "The red line is the latency SLO threshold (p95 <= 200 ms).",
    defaults={
        "custom": {"thresholdsStyle": {"mode": "line"}},
        **thresholds((None, "transparent"), (0.2, "red")),
    },
)
panel(
    "timeseries",
    "p95 latency by route",
    (16, 25, 8, 8),
    [
        (
            f"histogram_quantile(0.95, sum by (le, route) (rate({BUCKETS}[1m])))",
            "{{route}}",
        )
    ],
    "s",
)

row("Error budget burn rate (multi-window, multi-burn-rate)", 33)
panel(
    "timeseries",
    "Availability burn rate",
    (0, 34, 12, 9),
    [
        ('slo:sli_error:ratio_rate5m{slo="availability"} / 0.005', "5m"),
        ('slo:burn_rate:1h{slo="availability"}', "1h"),
        ('slo:sli_error:ratio_rate30m{slo="availability"} / 0.005', "30m"),
        ('slo:burn_rate:6h{slo="availability"}', "6h"),
    ],
    "x",
    "Critical page when 1h AND 5m > 14.4. Slack warning when 6h AND 30m > 6.",
    defaults={
        "custom": {"thresholdsStyle": {"mode": "dashed"}},
        **thresholds((None, "transparent"), (6, "orange"), (14.4, "red")),
    },
)
panel(
    "timeseries",
    "Latency burn rate",
    (12, 34, 12, 9),
    [
        ('slo:sli_error:ratio_rate5m{slo="latency"} / 0.05', "5m"),
        ('slo:burn_rate:1h{slo="latency"}', "1h"),
        ('slo:sli_error:ratio_rate30m{slo="latency"} / 0.05', "30m"),
        ('slo:burn_rate:6h{slo="latency"}', "6h"),
    ],
    "x",
    defaults={
        "custom": {"thresholdsStyle": {"mode": "dashed"}},
        **thresholds((None, "transparent"), (6, "orange"), (14.4, "red")),
    },
)
panel(
    "timeseries",
    "Error budget remaining (30-day window)",
    (0, 43, 12, 8),
    [("slo:error_budget_remaining:ratio30d", "{{slo}}")],
    "percentunit",
    defaults={
        "max": 1,
        "custom": {"thresholdsStyle": {"mode": "line"}},
        **thresholds((None, "red"), (0, "green")),
    },
)
logs = panel("logs", "Error logs (click a trace_id to open the trace in Tempo)", (12, 43, 12, 8), [])
logs["datasource"] = LOKI
logs["targets"] = [{"refId": "A", "datasource": LOKI, "expr": '{app="payment-api", level=~"ERROR|WARNING"}'}]
logs["options"] = {"showTime": True, "wrapLogMessage": True, "enableLogDetails": True}

dashboard = {
    "uid": "payment-api-sre",
    "title": "Payment API - SRE (RED, SLO & Error Budget)",
    "tags": ["sre", "slo", "payment-api"],
    "timezone": "browser",
    "refresh": "10s",
    "time": {"from": "now-1h", "to": "now"},
    "schemaVersion": 39,
    "panels": panels,
}
Path(__file__).with_name("payment-api-sre.json").write_text(json.dumps(dashboard, indent=2) + "\n")
