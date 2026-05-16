#!/usr/bin/env python3
"""Local storage helpers for budget analytics and interactive Q&A."""

from __future__ import annotations

import csv
import sqlite3
import sys
from pathlib import Path

from budget_core import DEFAULT_GROOMED_TRANSACTIONS_FILE, load_transactions, parse_posted_date

DEFAULT_DB_PATH = Path("data") / "budget_qa.db"
DEFAULT_GROOMED_EXPORT_PATH = Path("data") / "groomed_transactions.csv"


def discover_csv_files(csv_file: str | None) -> list[Path]:
    if csv_file:
        return [Path(csv_file)]

    if DEFAULT_GROOMED_TRANSACTIONS_FILE.exists():
        return [DEFAULT_GROOMED_TRANSACTIONS_FILE]

    sys.exit(
        f"Groomed transactions file not found: {DEFAULT_GROOMED_TRANSACTIONS_FILE}\n"
        "Run export_groomed_data.py first, or pass --csv-file explicitly."
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS transactions;

        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_file TEXT NOT NULL,
            source_row INTEGER,
            date_raw TEXT,
            posted_date TEXT,
            month TEXT,
            description_raw TEXT NOT NULL,
            description TEXT NOT NULL,
            merchant_normalized TEXT NOT NULL,
            amount REAL NOT NULL,
            direction TEXT NOT NULL,
            category TEXT NOT NULL,
            matched_rule TEXT
        );

        CREATE INDEX idx_transactions_month ON transactions(month);
        CREATE INDEX idx_transactions_category ON transactions(category);
        CREATE INDEX idx_transactions_merchant ON transactions(merchant_normalized);
        """
    )


def rebuild_cache(db_path: Path, csv_file: str | None) -> tuple[int, int]:
    csv_files = discover_csv_files(csv_file)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    inserted = 0
    skipped_unparseable_dates = 0

    try:
        init_db(conn)

        rows_to_insert: list[tuple[str, int | None, str | None, str, str | None, str | None, str, str, str, float, str, str | None]] = []
        for csv_path in csv_files:
            if not csv_path.exists():
                print(f"Skipping missing file: {csv_path}")
                continue

            transactions = load_transactions(str(csv_path))

            for tx in transactions:
                iso_date = tx.get("posted_date") or tx.get("date") or ""
                if not parse_posted_date(tx.get("date_raw") or iso_date):
                    skipped_unparseable_dates += 1

                month = tx.get("month")
                rows_to_insert.append(
                    (
                        tx.get("source_file") or csv_path.name,
                        tx.get("source_row"),
                        tx.get("date_raw"),
                        iso_date,
                        month,
                        tx["description_raw"],
                        tx["description"],
                        tx["merchant_normalized"],
                        tx["amount"],
                        tx["direction"],
                        tx["category"],
                        tx.get("matched_rule"),
                    )
                )

        conn.executemany(
            """
            INSERT INTO transactions (
                source_file, source_row, date_raw, posted_date, month,
                description_raw, description, merchant_normalized, amount, direction, category, matched_rule
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows_to_insert,
        )
        conn.commit()
        inserted = len(rows_to_insert)
    finally:
        conn.close()

    return inserted, skipped_unparseable_dates


def stats_context(conn: sqlite3.Connection) -> str:
    row = conn.execute(
        """
        SELECT
            COUNT(*) AS total_rows,
            COUNT(DISTINCT month) AS month_count,
            COALESCE(SUM(CASE WHEN category = 'Income' THEN amount ELSE 0 END), 0) AS income_total,
            COALESCE(SUM(CASE WHEN amount < 0 AND category != 'Transfer' THEN amount ELSE 0 END), 0) AS expense_total,
            COALESCE(SUM(CASE WHEN category = 'Transfer' THEN amount ELSE 0 END), 0) AS transfer_total
        FROM transactions
        """
    ).fetchone()

    top_categories = conn.execute(
        """
        SELECT category, SUM(amount) AS total
        FROM transactions
        GROUP BY category
        ORDER BY ABS(total) DESC
        LIMIT 12
        """
    ).fetchall()

    monthly = conn.execute(
        """
        SELECT month, category, SUM(amount) AS total
        FROM transactions
        WHERE month IS NOT NULL
        GROUP BY month, category
        ORDER BY month, category
        """
    ).fetchall()

    summary = [
        "Dataset summary:",
        f"- Total transactions: {row[0]}",
        f"- Distinct months: {row[1]}",
        f"- Income total: ${row[2]:.2f}",
        f"- Expense total (excl Transfer): ${row[3]:.2f}",
        f"- Net cash flow (Income + Expenses): ${row[2] + row[3]:.2f}",
        f"- Transfer total: ${row[4]:.2f}",
        "",
        "Category totals:",
    ]
    for category, total in top_categories:
        summary.append(f"- {category}: ${total:.2f}")

    summary.append("")
    summary.append("Monthly category totals:")
    for month, category, total in monthly:
        summary.append(f"- {month} | {category}: ${total:.2f}")

    return "\n".join(summary)


def export_transactions_csv(conn: sqlite3.Connection, output_path: Path) -> int:
    """Export the groomed canonical transaction table to CSV."""
    rows = conn.execute(
        """
        SELECT
            source_file,
            source_row,
            date_raw,
            posted_date,
            month,
            description_raw,
            description,
            merchant_normalized,
            amount,
            direction,
            category,
            matched_rule
        FROM transactions
        ORDER BY posted_date, source_file, source_row, id
        """
    ).fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "source_file",
                "source_row",
                "date_raw",
                "posted_date",
                "month",
                "description_raw",
                "description",
                "merchant_normalized",
                "amount",
                "direction",
                "category",
                "matched_rule",
            ]
        )
        writer.writerows(rows)

    return len(rows)
