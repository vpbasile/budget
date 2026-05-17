#!/usr/bin/env python3
"""Local storage helpers for budget analytics and interactive Q&A."""

from __future__ import annotations

import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from budget_core import (
    DEFAULT_CROSSWALK_FILE,
    categorize,
    load_merchant_crosswalk,
    load_transactions,
    parse_posted_date,
)

DEFAULT_DB_PATH = Path("data") / "budget_qa.db"
DEFAULT_TRANSACTIONS_EXPORT_PATH = Path("data") / "transactions_export.csv"
INTERNAL_TRANSFER_MAX_DAYS = 3
TRANSFER_KEYWORDS = (
    "TRANSFER",
    "XFER",
    "PAYMENT - THANK YOU",
    "ONLINE PAYMENT",
    "AUTOPAY",
)


def _parse_iso_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _looks_like_transfer_text(text: str | None) -> bool:
    value = (text or "").upper()
    return any(keyword in value for keyword in TRANSFER_KEYWORDS)


def mark_internal_transfer_pairs(transactions: list[dict]) -> int:
    """Mark mirrored in/out movements as Transfer when they look like internal transfers."""
    by_amount: dict[int, list[int]] = {}
    for idx, tx in enumerate(transactions):
        amount = float(tx.get("amount") or 0)
        if amount == 0:
            continue

        category = str(tx.get("category") or "")
        if category == "Income":
            continue

        if not (
            _looks_like_transfer_text(tx.get("description"))
            or _looks_like_transfer_text(tx.get("merchant_normalized"))
        ):
            continue

        cents = int(round(abs(amount) * 100))
        by_amount.setdefault(cents, []).append(idx)

    paired: set[int] = set()
    pair_count = 0

    for indices in by_amount.values():
        positives = [i for i in indices if float(transactions[i].get("amount") or 0) > 0 and i not in paired]
        negatives = [i for i in indices if float(transactions[i].get("amount") or 0) < 0 and i not in paired]

        for pos_idx in positives:
            if pos_idx in paired:
                continue

            pos_date = _parse_iso_date(transactions[pos_idx].get("posted_date") or transactions[pos_idx].get("date"))
            best_neg_idx: int | None = None
            best_gap = INTERNAL_TRANSFER_MAX_DAYS + 1

            for neg_idx in negatives:
                if neg_idx in paired:
                    continue

                neg_date = _parse_iso_date(transactions[neg_idx].get("posted_date") or transactions[neg_idx].get("date"))
                if pos_date is None or neg_date is None:
                    continue

                gap_days = abs((pos_date - neg_date).days)
                if gap_days <= INTERNAL_TRANSFER_MAX_DAYS and gap_days < best_gap:
                    best_gap = gap_days
                    best_neg_idx = neg_idx

            if best_neg_idx is None:
                continue

            for match_idx in (pos_idx, best_neg_idx):
                transactions[match_idx]["category"] = "Transfer"
                transactions[match_idx]["direction"] = "transfer"
                if not transactions[match_idx].get("matched_rule"):
                    transactions[match_idx]["matched_rule"] = "internal_transfer_pair"

            paired.add(pos_idx)
            paired.add(best_neg_idx)
            pair_count += 1

    return pair_count


def discover_csv_files(csv_file: str | None) -> list[Path]:
    if csv_file:
        return [Path(path.strip()) for path in csv_file.split(",") if path.strip()]

    history_files = sorted(Path("data").glob("history*.csv"))
    filtered_history = [path for path in history_files if "_nocat" not in path.name.lower()]
    if filtered_history:
        return filtered_history

    sys.exit(
        "No source transaction CSV files found.\n"
        "Expected files like data/history*.csv (excluding *_nocat.csv), or pass --csv-file explicitly."
    )


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        DROP TABLE IF EXISTS transactions;
        DROP TABLE IF EXISTS categories;

        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );

        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            posted_date TEXT,
            description TEXT NOT NULL,
            merchant_normalized TEXT NOT NULL,
            amount REAL NOT NULL,
            direction TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            matched_rule TEXT,
            FOREIGN KEY (category_id) REFERENCES categories(id)
        );

        CREATE INDEX idx_transactions_posted_date ON transactions(posted_date);
        CREATE INDEX idx_transactions_category_id ON transactions(category_id);
        CREATE INDEX idx_transactions_merchant ON transactions(merchant_normalized);
        """
    )


def rebuild_cache(
    db_path: Path,
    csv_file: str | None,
    crosswalk_path: Path = DEFAULT_CROSSWALK_FILE,
) -> tuple[int, int]:
    csv_files = discover_csv_files(csv_file)
    crosswalk = load_merchant_crosswalk(crosswalk_path)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    inserted = 0
    skipped_unparseable_dates = 0

    try:
        init_db(conn)

        prepared_rows: list[tuple[str, str, str, float, str, str, str | None]] = []
        for csv_path in csv_files:
            if not csv_path.exists():
                print(f"Skipping missing file: {csv_path}")
                continue

            transactions = load_transactions(str(csv_path))
            transactions = categorize(transactions, crosswalk)
            mark_internal_transfer_pairs(transactions)

            for tx in transactions:
                iso_date = tx.get("posted_date") or tx.get("date") or ""
                if not parse_posted_date(tx.get("date_raw") or iso_date):
                    skipped_unparseable_dates += 1

                description = str(tx.get("description") or "").strip()
                if tx.get("category") == "Transfer" and "PAYMENT - THANK YOU" in description.upper():
                    continue

                prepared_rows.append(
                    (
                        iso_date,
                        description,
                        tx["merchant_normalized"],
                        tx["amount"],
                        tx["direction"],
                        tx["category"],
                        tx.get("matched_rule"),
                    )
                )

        category_names = sorted({category for *_, category, _ in prepared_rows})
        conn.executemany(
            "INSERT OR IGNORE INTO categories(name) VALUES (?)",
            [(name,) for name in category_names],
        )

        category_rows = conn.execute("SELECT id, name FROM categories").fetchall()
        category_id_by_name = {name: category_id for category_id, name in category_rows}

        rows_to_insert = [
            (
                posted_date,
                description,
                merchant_normalized,
                amount,
                direction,
                category_id_by_name[category_name],
                matched_rule,
            )
            for posted_date, description, merchant_normalized, amount, direction, category_name, matched_rule in prepared_rows
        ]

        conn.executemany(
            """
            INSERT INTO transactions (
                posted_date, description, merchant_normalized, amount, direction, category_id, matched_rule
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
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
            COUNT(DISTINCT substr(t.posted_date, 1, 7)) AS month_count,
            COALESCE(SUM(CASE WHEN c.name = 'Income' THEN t.amount ELSE 0 END), 0) AS income_total,
            COALESCE(SUM(CASE WHEN t.amount < 0 AND c.name != 'Transfer' THEN t.amount ELSE 0 END), 0) AS expense_total,
            COALESCE(SUM(CASE WHEN c.name = 'Transfer' THEN t.amount ELSE 0 END), 0) AS transfer_total
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        """
    ).fetchone()

    top_categories = conn.execute(
        """
        SELECT c.name, SUM(t.amount) AS total
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        GROUP BY c.name
        ORDER BY ABS(total) DESC
        LIMIT 12
        """
    ).fetchall()

    monthly = conn.execute(
        """
        SELECT substr(t.posted_date, 1, 7) AS month, c.name, SUM(t.amount) AS total
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE t.posted_date IS NOT NULL AND t.posted_date != ''
        GROUP BY month, c.name
        ORDER BY month, c.name
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
    """Export the canonical transaction table to CSV."""
    rows = conn.execute(
        """
        SELECT
            t.posted_date,
            t.description,
            t.merchant_normalized,
            t.amount,
            t.direction,
            c.name AS category,
            t.matched_rule
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        ORDER BY t.posted_date, t.id
        """
    ).fetchall()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "posted_date",
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


def fetch_transactions(conn: sqlite3.Connection) -> list[dict]:
    """Load transaction rows from SQLite into the canonical dict shape."""
    rows = conn.execute(
        """
        SELECT
            t.posted_date,
            t.description,
            t.merchant_normalized,
            t.amount,
            t.direction,
            c.name AS category,
            t.matched_rule
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        ORDER BY t.posted_date, t.id
        """
    ).fetchall()

    return [
        {
            "date": posted_date,
            "posted_date": posted_date,
            "description": description,
            "merchant_normalized": merchant_normalized,
            "amount": amount,
            "direction": direction,
            "category": category,
            "matched_rule": matched_rule,
        }
        for (
            posted_date,
            description,
            merchant_normalized,
            amount,
            direction,
            category,
            matched_rule,
        ) in rows
    ]
