#!/usr/bin/env python3
"""Shared pure-ish budget data helpers."""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
DEFAULT_MODEL = "llama3.2"
DEFAULT_CROSSWALK_FILE = Path("data") / "merchant_crosswalk.md"
DEFAULT_GROOMED_TRANSACTIONS_FILE = Path("data") / "groomed_transactions.csv"
DEFAULT_UNMATCHED_REPORT_FILE = Path("data") / "unmatched_merchants_report.csv"
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%d/%m/%Y")


def load_merchant_crosswalk_csv(crosswalk_path: Path) -> list[tuple[re.Pattern[str], str]]:
    """Load merchant regex patterns and categories from a CSV crosswalk."""
    if not crosswalk_path.exists():
        sys.exit(f"❌  Crosswalk file not found: {crosswalk_path}")

    with open(crosswalk_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        expected = {"pattern", "category"}
        fieldnames = set(reader.fieldnames or [])
        if not expected.issubset(fieldnames):
            sys.exit(
                "❌  Crosswalk CSV must include headers: pattern, category\n"
                f"    Found: {', '.join(reader.fieldnames or [])}"
            )

        rows: list[tuple[re.Pattern[str], str]] = []
        for row in reader:
            pattern = (row.get("pattern") or "").strip()
            category = (row.get("category") or "").strip()
            if not pattern or not category:
                continue
            try:
                rows.append((re.compile(pattern, re.IGNORECASE), category))
            except re.error as exc:
                print(f"⚠️  Skipping invalid pattern {pattern!r}: {exc}", file=sys.stderr)

    if not rows:
        sys.exit(f"❌  Crosswalk file is empty: {crosswalk_path}")
    return rows


def _literal_contains_to_regex(value: str) -> str:
    """Convert a plain merchant token into a regex contains pattern."""
    token = value.strip().upper()
    escaped = re.escape(token)
    return escaped.replace(r"\ ", r"\s+")


def load_merchant_crosswalk_markdown(crosswalk_path: Path) -> list[tuple[re.Pattern[str], str]]:
    """Load a human-editable markdown crosswalk."""
    if not crosswalk_path.exists():
        sys.exit(f"❌  Crosswalk file not found: {crosswalk_path}")

    rows: list[tuple[re.Pattern[str], str]] = []
    current_category: str | None = None

    with open(crosswalk_path, encoding="utf-8-sig") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("### "):
                current_category = stripped[4:].strip()
                continue

            if not stripped.startswith("- ") or current_category is None:
                continue

            rule_text = stripped[2:].strip()
            if not rule_text:
                continue

            if rule_text.lower().startswith("re:"):
                pattern = rule_text[3:].strip()
            else:
                pattern = _literal_contains_to_regex(rule_text)

            if not pattern:
                continue
            try:
                rows.append((re.compile(pattern, re.IGNORECASE), current_category))
            except re.error as exc:
                print(f"⚠️  Skipping invalid pattern {pattern!r}: {exc}", file=sys.stderr)

    if not rows:
        sys.exit(f"❌  Crosswalk file is empty or invalid: {crosswalk_path}")
    return rows


def load_merchant_crosswalk(crosswalk_path: Path) -> list[tuple[re.Pattern[str], str]]:
    """Load merchant/category rules from CSV or human-readable markdown."""
    suffix = crosswalk_path.suffix.lower()
    if suffix == ".csv":
        return load_merchant_crosswalk_csv(crosswalk_path)
    if suffix in {".md", ".markdown"}:
        return load_merchant_crosswalk_markdown(crosswalk_path)

    sys.exit(
        "❌  Unsupported crosswalk format. Use .csv or .md\n"
        f"    Received: {crosswalk_path}"
    )


def parse_amount(raw_amount: str) -> float | None:
    """Parse currency values like $123.45, -$123.45, or ($123.45)."""
    if raw_amount is None:
        return None

    value = raw_amount.strip()
    if not value:
        return None

    is_negative = value.startswith("(") and value.endswith(")")
    if is_negative:
        value = value[1:-1]

    value = value.replace("$", "").replace(",", "").strip()

    try:
        amount = float(value)
    except ValueError:
        return None

    return -abs(amount) if is_negative else amount


def parse_posted_date(raw_date: str) -> str | None:
    """Normalize posted dates to ISO format when possible."""
    value = (raw_date or "").strip()
    if not value:
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def normalize_merchant(description: str) -> str:
    """Normalize raw description text for crosswalk matching."""
    normalized = description.upper()
    normalized = re.sub(r"\(CARD XX\d+\)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def category_from_crosswalk(description: str, crosswalk: list[tuple[re.Pattern[str], str]]) -> str | None:
    """Return a deterministic category when a merchant pattern is recognized."""
    merchant = normalize_merchant(description)
    for pattern, category in crosswalk:
        if pattern.search(merchant):
            return category
    return None


def crosswalk_match(description: str, crosswalk: list[tuple[re.Pattern[str], str]]) -> tuple[str | None, str | None]:
    """Return the first matching category and its raw regex rule."""
    merchant = normalize_merchant(description)
    for pattern, category in crosswalk:
        if pattern.search(merchant):
            return category, pattern.pattern
    return None, None


def load_transactions(csv_path: str) -> list[dict]:
    """Load transactions from either raw bank CSVs or the groomed canonical CSV."""
    transactions = []
    source_file = Path(csv_path).name
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = {name.strip() for name in (reader.fieldnames or []) if name}
        is_groomed = {
            "source_file",
            "source_row",
            "date_raw",
            "posted_date",
            "description",
            "merchant_normalized",
            "amount",
            "direction",
            "category",
        }.issubset(fieldnames)

        for source_row, row in enumerate(reader, start=2):
            if is_groomed:
                raw_amount = row.get("amount")
                amount = parse_amount(raw_amount)
                if amount is None:
                    continue

                posted_date_raw = (row.get("date_raw") or row.get("posted_date") or "").strip()
                posted_date = (row.get("posted_date") or "").strip() or parse_posted_date(posted_date_raw) or posted_date_raw
                description_raw = (row.get("description_raw") or row.get("description") or "").strip()
                merchant_normalized = (row.get("merchant_normalized") or "").strip() or normalize_merchant(description_raw)
                direction = (row.get("direction") or "").strip().lower()
                if not direction:
                    direction = "income" if amount > 0 else "expense" if amount < 0 else "flat"

                transactions.append(
                    {
                        "source_file": (row.get("source_file") or source_file).strip(),
                        "source_row": int(row.get("source_row") or source_row),
                        "date_raw": posted_date_raw,
                        "date": posted_date,
                        "posted_date": posted_date,
                        "month": (row.get("month") or "").strip() or (posted_date[:7] if len(posted_date) >= 7 and posted_date[4] == "-" else None),
                        "description_raw": description_raw,
                        "description": (row.get("description") or description_raw).strip(),
                        "merchant_normalized": merchant_normalized,
                        "amount": amount,
                        "direction": direction,
                        "category": (row.get("category") or "Other").strip() or "Other",
                        "matched_rule": (row.get("matched_rule") or "").strip() or None,
                    }
                )
                continue

            raw_amount = row.get("Amount")
            amount = parse_amount(raw_amount)
            if amount is None:
                continue

            posted_date_raw = (row.get("Posted Date") or row.get("Date") or "").strip()
            posted_date = parse_posted_date(posted_date_raw) or posted_date_raw
            description_raw = (row.get("Description") or "").strip()
            merchant_normalized = normalize_merchant(description_raw)

            transactions.append(
                {
                    "source_file": source_file,
                    "source_row": source_row,
                    "date_raw": posted_date_raw,
                    "date": posted_date,
                    "posted_date": posted_date,
                    "month": posted_date[:7] if len(posted_date) >= 7 and posted_date[4] == "-" else None,
                    "description_raw": description_raw,
                    "description": description_raw,
                    "merchant_normalized": merchant_normalized,
                    "amount": amount,
                    "direction": "income" if amount > 0 else "expense" if amount < 0 else "flat",
                }
            )

    return transactions


def categorize(transactions: list[dict], crosswalk: list[tuple[re.Pattern[str], str]]) -> list[dict]:
    """Categorize using merchant crosswalk only; unmatched rows become Other."""
    result: list[dict] = []
    for tx in transactions:
        category, matched_rule = crosswalk_match(tx["description"], crosswalk)
        enriched = {**tx, "category": category or "Other", "matched_rule": matched_rule}
        if enriched["category"] == "Transfer":
            enriched["direction"] = "transfer"
        result.append(enriched)
    return result


def aggregate(transactions: list[dict], all_categories: list[str] | None = None) -> dict:
    """Compute monthly & category-level spending summaries."""
    monthly: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    category_totals: dict[str, float] = defaultdict(float, {cat: 0.0 for cat in (all_categories or [])})
    skipped = 0

    for tx in transactions:
        posted_date = tx.get("posted_date") or tx.get("date") or tx.get("date_raw") or ""
        dt = None
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(posted_date, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            skipped += 1
            continue

        month_key = dt.strftime("%Y-%m")
        cat = tx["category"]
        amt = tx["amount"]
        monthly[month_key][cat] += amt
        category_totals[cat] += amt

    if skipped:
        print(f"⚠️  {skipped} transaction(s) skipped due to unparseable dates.", file=sys.stderr)

    return {
        "monthly": {m: dict(cats) for m, cats in sorted(monthly.items())},
        "category_totals": dict(category_totals),
    }


def ollama_chat(messages: list[dict], model: str) -> str:
    """Send a chat request to Ollama and return the assistant's reply."""
    payload = {"model": model, "messages": messages, "stream": False}
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        sys.exit(
            "❌  Cannot reach Ollama at http://localhost:11434\n"
            "    Make sure Ollama is running:  ollama serve"
        )
    return resp.json()["message"]["content"]
