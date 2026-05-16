#!/usr/bin/env python3
"""Export the groomed canonical transaction table to CSV."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from budget_core import DEFAULT_GROOMED_TRANSACTIONS_FILE
from budget_storage import (
    DEFAULT_DB_PATH,
    DEFAULT_GROOMED_EXPORT_PATH,
    export_transactions_csv,
    rebuild_cache,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export the groomed canonical transaction table to CSV.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help=f"SQLite cache path (default: {DEFAULT_DB_PATH})")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_GROOMED_EXPORT_PATH),
        help=f"Output CSV path (default: {DEFAULT_GROOMED_EXPORT_PATH})",
    )
    parser.add_argument(
        "--csv-file",
        default=str(DEFAULT_GROOMED_TRANSACTIONS_FILE),
        help=f"Transactions CSV input (default: {DEFAULT_GROOMED_TRANSACTIONS_FILE})",
    )
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the SQLite cache before exporting")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    output_path = Path(args.output)

    if args.rebuild or not db_path.exists():
        print("Building local SQLite cache from CSV data...")
        inserted, skipped = rebuild_cache(db_path, args.csv_file)
        print(f"Cache ready: {inserted} row(s), {skipped} row(s) with unparseable date format.")

    conn = sqlite3.connect(db_path)
    try:
        count = export_transactions_csv(conn, output_path)
    finally:
        conn.close()

    print(f"Exported {count} groomed transaction(s) to {output_path}")


if __name__ == "__main__":
    main()
