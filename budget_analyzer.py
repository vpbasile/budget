#!/usr/bin/env python3
"""Budget Analyzer using Ollama."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from budget_core import (
    DEFAULT_GROOMED_TRANSACTIONS_FILE,
    DEFAULT_MODEL,
    DEFAULT_UNMATCHED_REPORT_FILE,
    aggregate,
    load_transactions,
)
from budget_reporting import generate_budget_report
from unmatched_report import write_unmatched_merchants_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze bank transactions and generate a budget using Ollama.")
    parser.add_argument(
        "--transactions-file",
        default=str(DEFAULT_GROOMED_TRANSACTIONS_FILE),
        help=f"Path to groomed transactions CSV (default: {DEFAULT_GROOMED_TRANSACTIONS_FILE})",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--output", default="data/budget_report.md", help="Output file for the budget report")
    parser.add_argument(
        "--unmatched-report",
        default=str(DEFAULT_UNMATCHED_REPORT_FILE),
        help=f"Output CSV for unmatched merchant rollup (default: {DEFAULT_UNMATCHED_REPORT_FILE})",
    )
    parser.add_argument(
        "--unmatched-min-count",
        type=int,
        default=1,
        help="Only include unmatched merchants with at least this many occurrences (default: 1)",
    )
    args = parser.parse_args()

    transactions_path = Path(args.transactions_file)
    if not transactions_path.exists():
        sys.exit(f"❌  Groomed transactions file not found: {transactions_path}")

    print(f"📂  Loading groomed transactions from {transactions_path}...")
    enriched = load_transactions(str(transactions_path))
    print(f"    Total: {len(enriched)} transactions.")

    matched_count = sum(1 for tx in enriched if tx["category"] != "Other")
    other_count = len(enriched) - matched_count
    match_pct = (matched_count / len(enriched) * 100) if enriched else 0.0
    print(
        f"    Categorized rows: {matched_count}/{len(enriched)} "
        f"({match_pct:.1f}%), Other: {other_count}"
    )

    unmatched_report_path = Path(args.unmatched_report)
    report_rows = write_unmatched_merchants_report(
        enriched,
        unmatched_report_path,
        min_count=max(1, args.unmatched_min_count),
    )
    print(f"    Unmatched report: {unmatched_report_path} ({report_rows} rows)")

    print("\n📊  Aggregating spending data...")
    all_categories = list(dict.fromkeys(tx.get("category") or "Other" for tx in enriched))
    agg = aggregate(enriched, all_categories)

    print("💡  Generating budget report...")
    report = generate_budget_report(agg, args.model)

    output_path = Path(args.output)
    output_path.write_text(report, encoding="utf-8")
    print(f"\n✅  Budget report saved to: {output_path}")
    print("\n" + "─" * 60)
    print(report)


if __name__ == "__main__":
    main()
