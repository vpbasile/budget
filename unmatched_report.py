#!/usr/bin/env python3
"""Helpers for writing unmatched merchant reports."""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path


def normalize_merchant_for_report(description: str) -> str:
    """Normalize merchant descriptions so similar rows are grouped together."""
    normalized = description.upper()
    normalized = re.sub(r"\(CARD XX\d+\)", "", normalized)
    normalized = re.sub(r"\b\d{3,}\b", "<N>", normalized)
    normalized = re.sub(r"\b\d{2}/\d{2}\b", "<MMDD>", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def write_unmatched_merchants_report(
    transactions: list[dict],
    output_path: Path,
    min_count: int = 1,
    top_n: int = 200,
) -> int:
    """Write a CSV report of unmatched transactions and return number of rows written."""
    counts: Counter[str] = Counter()
    samples: dict[str, str] = {}

    for tx in transactions:
        if tx.get("category") != "Other":
            continue

        description = str(tx.get("description", "")).strip()
        if not description:
            continue

        key = normalize_merchant_for_report(description)
        counts[key] += 1
        samples.setdefault(key, description)

    rows = [(merchant, count, samples[merchant]) for merchant, count in counts.most_common() if count >= min_count]
    if top_n > 0:
        rows = rows[:top_n]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["count", "normalized_merchant", "example_description"])
        for merchant, count, sample in rows:
            writer.writerow([count, merchant, sample])

    return len(rows)
