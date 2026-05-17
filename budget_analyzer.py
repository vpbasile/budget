#!/usr/bin/env python3
"""Budget Analyzer using Ollama."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from budget_core import (
    DEFAULT_CROSSWALK_FILE,
    DEFAULT_MODEL,
    DEFAULT_UNMATCHED_REPORT_FILE,
    aggregate,
)
from budget_reporting import generate_budget_report
from budget_storage import DEFAULT_DB_PATH, fetch_transactions, rebuild_cache
from unmatched_report import write_unmatched_merchants_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze bank transactions and generate a budget using Ollama.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help=f"SQLite DB path (default: {DEFAULT_DB_PATH})")
    parser.add_argument(
        "--csv-file",
        default=None,
        help="Source CSV file(s), comma-separated. Defaults to data/history*.csv excluding *_nocat.csv.",
    )
    parser.add_argument(
        "--crosswalk",
        default=str(DEFAULT_CROSSWALK_FILE),
        help=f"Merchant/category crosswalk path (default: {DEFAULT_CROSSWALK_FILE})",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Rebuild the SQLite database from source CSV data before analysis.",
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

    db_path = Path(args.db_path)
    if args.rebuild or not db_path.exists():
        print("Building local SQLite cache from source CSV data...")
        inserted, skipped = rebuild_cache(db_path, args.csv_file, Path(args.crosswalk))
        print(f"Cache ready: {inserted} row(s), {skipped} row(s) with unparseable date format.")

    if not db_path.exists():
        sys.exit(f"❌  SQLite database not found: {db_path}")

    print(f"📂  Loading transactions from SQLite DB: {db_path}...")
    conn = sqlite3.connect(db_path)
    try:
        enriched = fetch_transactions(conn)
    finally:
        conn.close()

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
