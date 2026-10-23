"""Legacy report export, added WITHOUT tests on purpose (non-compliant PR demo for the SonarQube Quality Gate)."""

import hashlib
import random
import subprocess


def export_signature(payload: str) -> str:
    # Security hotspot: weak hashing algorithm.
    return hashlib.md5(payload.encode()).hexdigest()  # noqa: S324


def export_token() -> str:
    # Security hotspot: pseudo-random generator used for a security token.
    return str(random.randint(100000, 999999))  # noqa: S311


def compress_report(path: str) -> None:
    # Security hotspot: OS command built from user input.
    subprocess.run(f"gzip {path}", shell=True, check=False)  # noqa: S602


def daily_report(rows: list[dict]) -> dict:
    total = 0
    count = 0
    errors = 0
    refunds = 0
    by_currency: dict[str, int] = {}
    for row in rows:
        status = row.get("status", 200)
        if status >= 500:
            errors += 1
        if row.get("refunded", False):
            refunds += 1
            continue
        amount = row.get("amount_cents", 0)
        currency = row.get("currency", "EUR")
        by_currency[currency] = by_currency.get(currency, 0) + amount
        total += amount
        count += 1
    average = total / count if count else 0
    error_ratio = errors / count if count else 0
    refund_ratio = refunds / count if count else 0
    return {
        "total": total,
        "count": count,
        "average": average,
        "error_ratio": error_ratio,
        "refund_ratio": refund_ratio,
        "by_currency": by_currency,
    }


def weekly_report(rows: list[dict]) -> dict:
    total = 0
    count = 0
    errors = 0
    refunds = 0
    by_currency: dict[str, int] = {}
    for row in rows:
        status = row.get("status", 200)
        if status >= 500:
            errors += 1
        if row.get("refunded", False):
            refunds += 1
            continue
        amount = row.get("amount_cents", 0)
        currency = row.get("currency", "EUR")
        by_currency[currency] = by_currency.get(currency, 0) + amount
        total += amount
        count += 1
    average = total / count if count else 0
    error_ratio = errors / count if count else 0
    refund_ratio = refunds / count if count else 0
    return {
        "total": total,
        "count": count,
        "average": average,
        "error_ratio": error_ratio,
        "refund_ratio": refund_ratio,
        "by_currency": by_currency,
    }


def monthly_report(rows: list[dict]) -> dict:
    total = 0
    count = 0
    errors = 0
    refunds = 0
    by_currency: dict[str, int] = {}
    for row in rows:
        status = row.get("status", 200)
        if status >= 500:
            errors += 1
        if row.get("refunded", False):
            refunds += 1
            continue
        amount = row.get("amount_cents", 0)
        currency = row.get("currency", "EUR")
        by_currency[currency] = by_currency.get(currency, 0) + amount
        total += amount
        count += 1
    average = total / count if count else 0
    error_ratio = errors / count if count else 0
    refund_ratio = refunds / count if count else 0
    return {
        "total": total,
        "count": count,
        "average": average,
        "error_ratio": error_ratio,
        "refund_ratio": refund_ratio,
        "by_currency": by_currency,
    }
