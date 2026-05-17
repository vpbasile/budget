#!/usr/bin/env python3
"""Build the SQLite transaction database from source CSV data."""

from __future__ import annotations

import argparse
from pathlib import Path

from budget_core import DEFAULT_CROSSWALK_FILE
from budget_storage import (
    DEFAULT_DB_PATH,
    rebuild_cache,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the SQLite transaction database from source CSV data.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH), help=f"SQLite cache path (default: {DEFAULT_DB_PATH})")
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    crosswalk_path = Path(args.crosswalk)

    print("Building local SQLite cache from source CSV data...")
    inserted, skipped = rebuild_cache(db_path, args.csv_file, crosswalk_path)
    print(f"Cache ready: {inserted} row(s), {skipped} row(s) with unparseable date format.")

    print(f"SQLite database updated: {db_path}")


if __name__ == "__main__":
    main()
