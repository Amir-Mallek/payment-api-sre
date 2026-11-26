#!/usr/bin/env python3
"""PayFlex Quality Gate: classifies every pipeline indicator as OK, WARNING (non-critical) or CRITICAL.

Each stage of the pipeline evaluates its own reports right after producing them:

    quality_gate.py unit junit.xml coverage.xml
    quality_gate.py sonar sonar-gate.json sonar-blocking.json sonar-smells.json
    quality_gate.py secrets <source|artifact|logs> gitleaks-report.json
    quality_gate.py integration newman-report.json
    quality_gate.py perf k6-summary.json

A check writes gate-results/<stage>.json, prints GitHub annotations (::warning / ::error), appends a table
to the job summary and exits 1 on a CRITICAL finding: the job fails, so every job that depends on it is
skipped (fail fast, nothing is deployed). WARNING findings never stop the pipeline.

The last job always runs and aggregates every result into a quality report, or into an incident report
naming the exact cause when the pipeline was stopped:

    quality_gate.py report gate-results/ --needs "$NEEDS_JSON"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET  # noqa: S405 - parses reports produced by this pipeline only
from pathlib import Path

# ---- Thresholds (assignment, step 3) ----------------------------------------------------------------
COVERAGE_TARGET = 80.0  # >= 80 %: OK
COVERAGE_CRITICAL = 70.0  # 70-80 %: WARNING, < 70 %: CRITICAL
P95_TARGET_MS = 200.0  # p95 < 200 ms: OK
P95_CRITICAL_MS = 500.0  # 200-500 ms: WARNING, > 500 ms: CRITICAL
ERRORS_TARGET_PCT = 1.0  # < 1 %: OK
ERRORS_CRITICAL_PCT = 2.0  # 1-2 %: WARNING, > 2 %: CRITICAL
MAX_LEAKS = 0  # tolerated leaks: the confidentiality rate must be 100 %

OK, WARNING, CRITICAL = "OK", "WARNING", "CRITICAL"
RANK = {OK: 0, WARNING: 1, CRITICAL: 2}
BADGE = {OK: "🟢 OK", WARNING: "🟠 NON-CRITIQUE", CRITICAL: "🔴 CRITIQUE"}

STAGES = {  # pipeline order
    "secrets-source": "Confidentialité - code source et configuration",
    "unit": "Tests unitaires et couverture",
    "sonar": "Analyse statique SonarQube",
    "secrets-artifact": "Confidentialité - artefact (image Docker)",
    "integration": "Tests d'intégration Newman",
    "secrets-logs": "Confidentialité - logs applicatifs",
    "perf": "Tests de performance k6",
}
JOB_TITLES = {
    "secrets-scan": "Gitleaks - code source et configuration",
    "lint-test": "Lint et tests unitaires",
    "policies": "Helm lint et politiques Gatekeeper",
    "sonarqube": "SonarQube et Quality Gate",
    "build-image": "Build Docker, Trivy et scan de l'artefact",
    "integration-tests": "Tests d'intégration Newman",
    "performance-tests": "Tests de performance k6",
}
RESULTS_DIR = Path(os.getenv("GATE_RESULTS_DIR", "gate-results"))


def indicator(name: str, value: str, threshold: str, level: str, detail: str = "") -> dict:
    return {"name": name, "value": value, "threshold": threshold, "level": level, "detail": detail}


def worst(levels) -> str:
    return max(levels, key=RANK.__getitem__, default=OK)


def classify_high(value: float, target: float, critical: float) -> str:
    """Level of a metric where higher is worse."""
    if value > critical:
        return CRITICAL
    return WARNING if value >= target else OK


# ---- Checks ------------------------------------------------------------------------------------------
def check_unit(junit: str, coverage: str) -> list[dict]:
    suites = ET.parse(junit).getroot()  # noqa: S314
    suite_list = [suites] if suites.tag == "testsuite" else list(suites)
    total = sum(int(s.get("tests", 0)) for s in suite_list)
    failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suite_list)
    cov = float(ET.parse(coverage).getroot().get("line-rate", 0)) * 100  # noqa: S314
    if cov < COVERAGE_CRITICAL:
        cov_level = CRITICAL
    elif cov < COVERAGE_TARGET:
        cov_level = WARNING
    else:
        cov_level = OK
    return [
        indicator(
            "Tests unitaires en échec",
            f"{failed} / {total}",
            "0",
            CRITICAL if failed else OK,
            "régression détectée par pytest" if failed else "",
        ),
        indicator(
            "Couverture de code",
            f"{cov:.1f} %",
            f"OK >= {COVERAGE_TARGET:.0f} % · critique < {COVERAGE_CRITICAL:.0f} %",
            cov_level,
            f"Attention, couverture à {cov:.0f} %" if cov_level == WARNING else "",
        ),
    ]


def check_sonar(gate: str, blocking: str, smells: str) -> list[dict]:
    status = json.loads(Path(gate).read_text()).get("projectStatus", {})
    failing = [c for c in status.get("conditions", []) if c.get("status") == "ERROR"]
    detail = ", ".join(
        f"{c['metricKey']} = {c.get('actualValue', '?')} ({c['comparator']} {c['errorThreshold']})"
        for c in failing
    )
    n_blocking = json.loads(Path(blocking).read_text()).get("total", 0)
    n_smells = json.loads(Path(smells).read_text()).get("total", 0)
    return [
        indicator(
            "Quality Gate SonarQube",
            status.get("status", "?"),
            "OK",
            CRITICAL if status.get("status") != "OK" else OK,
            detail,
        ),
        indicator(
            "Bugs / vulnérabilités bloquants",
            str(n_blocking),
            "0",
            CRITICAL if n_blocking else OK,
            "bug bloquant ou critique (ex. NullPointer potentiel)" if n_blocking else "",
        ),
        indicator(
            "Code smells (dette technique)",
            str(n_smells),
            "0 (non bloquant)",
            WARNING if n_smells else OK,
            f"{n_smells} code smell(s) à traiter" if n_smells else "",
        ),
    ]


def confidentiality_rate(leaks: int, tolerated: int = MAX_LEAKS) -> float:
    """Taux = (1 - fuites / seuil toléré) x 100 %, borné à [0, 100].

    With a tolerated threshold of 0 the ratio is undefined: 0 leak gives 100 %, any leak gives 0 %.
    """
    if leaks == 0:
        return 100.0
    if tolerated == 0:
        return 0.0
    return max(0.0, (1 - leaks / tolerated) * 100)


def check_secrets(scope: str, report: str) -> list[dict]:
    if not Path(report).exists():  # fail closed: a scan that did not run proves nothing
        return [
            indicator(
                f"Taux de confidentialité ({scope})",
                "inconnu",
                "100 %",
                CRITICAL,
                "rapport Gitleaks absent : le scan n'a pas été exécuté",
            )
        ]
    text = Path(report).read_text().strip()
    findings = json.loads(text) if text else []
    rate = confidentiality_rate(len(findings))
    where = "; ".join(f"{f.get('RuleID')} dans {f.get('File')}:{f.get('StartLine')}" for f in findings[:10])
    return [
        indicator(
            f"Taux de confidentialité ({scope})",
            f"{rate:.0f} % ({len(findings)} fuite(s))",
            "100 %",
            CRITICAL if rate < 100 else OK,
            where,
        )
    ]


def check_integration(report: str) -> list[dict]:
    run = json.loads(Path(report).read_text())["run"]
    stats = run["stats"]
    failed = stats["assertions"]["failed"] + stats["requests"]["failed"]
    detail = "; ".join(
        f"{f['source'].get('name', '?')}: {f['error'].get('message', '')}"
        for f in run.get("failures", [])[:10]
    )
    return [
        indicator(
            "Assertions API en échec",
            f"{failed} / {stats['assertions']['total']}",
            "0",
            CRITICAL if failed else OK,
            detail,
        )
    ]


def check_perf(summary: str) -> list[dict]:
    metrics = json.loads(Path(summary).read_text())["metrics"]
    p95 = float(metrics["http_req_duration"]["p(95)"])
    errors = float(metrics["http_req_failed"]["value"]) * 100
    reqs = int(metrics["http_reqs"]["count"])
    p95_level = classify_high(p95, P95_TARGET_MS, P95_CRITICAL_MS)
    err_level = classify_high(errors, ERRORS_TARGET_PCT, ERRORS_CRITICAL_PCT)
    return [
        indicator(
            "Latence p95",
            f"{p95:.0f} ms",
            f"OK < {P95_TARGET_MS:.0f} ms · critique > {P95_CRITICAL_MS:.0f} ms",
            p95_level,
            f"{reqs} requêtes" if p95_level == OK else f"p95 à {p95:.0f} ms sur {reqs} requêtes",
        ),
        indicator(
            "Taux d'erreur HTTP",
            f"{errors:.2f} %",
            f"OK < {ERRORS_TARGET_PCT:.0f} % · critique > {ERRORS_CRITICAL_PCT:.0f} %",
            err_level,
        ),
    ]


# ---- Output ------------------------------------------------------------------------------------------
def table(rows: list[tuple[str, dict]]) -> str:
    lines = ["| Étape | Indicateur | Valeur | Seuil | Niveau | Détail |", "|---|---|---|---|---|---|"]
    for stage_title, i in rows:
        lines.append(
            f"| {stage_title} | {i['name']} | {i['value']} | {i['threshold']} | {BADGE[i['level']]} "
            f"| {i['detail']} |"
        )
    return "\n".join(lines)


def write_summary(markdown: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(markdown + "\n")


def annotate(level: str, title: str, message: str) -> None:
    if level == WARNING:
        print(f"::warning title=Quality Gate (non-critique) - {title}::{message}")
    elif level == CRITICAL:
        print(f"::error title=Quality Gate (CRITIQUE) - {title}::{message}")


def emit(stage: str, indicators: list[dict]) -> int:
    level = worst(i["level"] for i in indicators)
    result = {"stage": stage, "title": STAGES[stage], "level": level, "indicators": indicators}
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"{stage}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    for i in indicators:
        message = f"{i['name']} = {i['value']} (seuil {i['threshold']}) {i['detail']}"
        annotate(i["level"], STAGES[stage], message)
    rows = [(STAGES[stage], i) for i in indicators]
    write_summary(f"### {BADGE[level]} - {STAGES[stage]}\n\n" + table(rows))
    print(f"[quality-gate] {stage}: {level}")
    for i in indicators:
        print(f"  - {i['name']}: {i['value']} -> {i['level']} {i['detail']}")
    return 1 if level == CRITICAL else 0


def report(results_dir: str, needs_json: str, out: str) -> int:
    results = {}
    for path in sorted(Path(results_dir).glob("*.json")):
        data = json.loads(path.read_text())
        results[data["stage"]] = data
    needs = json.loads(needs_json) if needs_json else {}

    rows = [(results[s]["title"], i) for s in STAGES if s in results for i in results[s]["indicators"]]
    criticals = [
        (results[s]["title"], i)
        for s in STAGES
        if s in results
        for i in results[s]["indicators"]
        if i["level"] == CRITICAL
    ]
    warnings = [(t, i) for t, i in rows if i["level"] == WARNING]
    failed_jobs = [j for j, v in needs.items() if v.get("result") in ("failure", "cancelled")]
    skipped_jobs = [j for j, v in needs.items() if v.get("result") == "skipped"]
    blocked = bool(criticals or failed_jobs)

    run_url = ""
    if os.getenv("GITHUB_RUN_ID"):
        repo_url = f"{os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}"
        run_url = f"{repo_url}/actions/runs/{os.getenv('GITHUB_RUN_ID')}"
    verdict = (
        "🔴 PIPELINE BLOQUÉ - déploiement annulé"
        if blocked
        else ("🟠 VALIDÉ AVEC ALERTES" if warnings else "🟢 VALIDÉ - tous les critères au vert")
    )

    md = [f"# Quality Gate PayFlex : {verdict}", ""]
    md.append(f"Commit `{os.getenv('GITHUB_SHA', 'local')[:7]}` · run {run_url or 'local'}")
    md.append("")
    if blocked:
        md += ["## Rapport d'incident", ""]
        if criticals:
            title, first = criticals[0]
            md.append(
                f"**Cause du blocage :** {title} - {first['name']} = **{first['value']}** "
                f"(seuil : {first['threshold']})."
            )
            if first["detail"]:
                md.append(f"\n**Détail :** {first['detail']}")
            for title, i in criticals[1:]:
                md.append(f"\nAutre erreur critique : {title} - {i['name']} = {i['value']} ({i['detail']})")
        no_result = [
            j for j in failed_jobs if not any(results.get(s, {}).get("level") == CRITICAL for s in STAGES)
        ]
        for job in failed_jobs:
            if job in no_result or not criticals:
                md.append(f"\n**Job en échec :** {JOB_TITLES.get(job, job)} (voir les logs du job).")
        if skipped_jobs:
            md.append(
                "\n**Étapes annulées (fail fast) :** "
                + ", ".join(JOB_TITLES.get(j, j) for j in skipped_jobs)
                + "."
            )
        md.append("\n**Conséquence :** aucune image publiée, aucun déploiement (GitOps non déclenché).")
        md.append("")
    if warnings:
        md += ["## Alertes non critiques (le pipeline continue)", ""]
        md += [f"- {t} : {i['name']} = {i['value']} - {i['detail'] or i['threshold']}" for t, i in warnings]
        md.append("")
    md += ["## Indicateurs", "", table(rows) if rows else "_Aucun indicateur collecté._", ""]
    md += ["## Jobs", "", "| Job | Résultat |", "|---|---|"]
    md += [f"| {JOB_TITLES.get(j, j)} | {v.get('result')} |" for j, v in needs.items()]

    text = "\n".join(md) + "\n"
    Path(out).write_text(text, encoding="utf-8")
    write_summary(text)
    print(text)
    for t, i in warnings:
        annotate(WARNING, t, f"{i['name']} = {i['value']}")
    return 1 if blocked else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("unit")
    p.add_argument("junit")
    p.add_argument("coverage")
    p = sub.add_parser("sonar")
    p.add_argument("gate")
    p.add_argument("blocking")
    p.add_argument("smells")
    p = sub.add_parser("secrets")
    p.add_argument("scope", choices=["source", "artifact", "logs"])
    p.add_argument("report")
    p = sub.add_parser("integration")
    p.add_argument("report")
    p = sub.add_parser("perf")
    p.add_argument("summary")
    p = sub.add_parser("report")
    p.add_argument("results_dir")
    p.add_argument("--needs", default="")
    p.add_argument("--out", default="quality-report.md")
    args = parser.parse_args(argv)

    if args.cmd == "unit":
        return emit("unit", check_unit(args.junit, args.coverage))
    if args.cmd == "sonar":
        return emit("sonar", check_sonar(args.gate, args.blocking, args.smells))
    if args.cmd == "secrets":
        return emit(f"secrets-{args.scope}", check_secrets(args.scope, args.report))
    if args.cmd == "integration":
        return emit("integration", check_integration(args.report))
    if args.cmd == "perf":
        return emit("perf", check_perf(args.summary))
    return report(args.results_dir, args.needs, args.out)


if __name__ == "__main__":
    sys.exit(main())
