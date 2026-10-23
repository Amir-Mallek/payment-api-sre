"""Turns /api/qualitygates/project_status JSON (stdin) into a Markdown table for the job summary."""

import json
import sys

status = json.load(sys.stdin).get("projectStatus", {})
icon = {"OK": "PASSED", "ERROR": "FAILED"}.get(status.get("status"), status.get("status", "?"))
print(f"## SonarQube Quality Gate: {icon}\n")
print("| Metric | Status | Actual | Threshold |")
print("|---|---|---|---|")
for c in status.get("conditions", []):
    print(f"| {c['metricKey']} | {c['status']} | {c.get('actualValue', '-')} | {c['comparator']} {c['errorThreshold']} |")
