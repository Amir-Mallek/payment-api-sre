# Non-compliant PR (SonarQube Quality Gate demo)

`report_export.py` is copied into `app/` on a branch to open a pull request that **must be blocked**:

| Gate condition | What the file does |
|---|---|
| Security hotspot not reviewed | `hashlib.md5`, `random` for a token, `subprocess(..., shell=True)` |
| Duplication > 3% | `daily_report`, `weekly_report` and `monthly_report` are copies |
| Coverage < 85% on new code | no unit test for the new module |

```bash
git checkout -b feature/report-export
cp demo/bad-pr/report_export.py app/
git add app/report_export.py && git commit -m "feat: add report export"
git push -u origin feature/report-export
gh pr create --fill --base main
```

Expected result in GitHub Actions:
- `Lint & unit tests`: fails (`--cov-fail-under=85`, total coverage drops to ~75%).
- `SonarQube analysis & Quality Gate`: **FAILED** (hotspots reviewed 0% < 100%, duplication 16.5% > 3%,
  coverage 75.5% < 85%). The job summary shows the table of conditions.
- `Docker build, Trivy scan, push` and `GitOps`: skipped, nothing is deployed.
