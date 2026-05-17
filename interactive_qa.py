#!/usr/bin/env python3
"""Interactive Ollama Q&A over categorized budget data."""

from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path

from budget_core import DEFAULT_CROSSWALK_FILE, DEFAULT_MODEL, ollama_chat
from budget_storage import (
    DEFAULT_DB_PATH,
    DEFAULT_TRANSACTIONS_EXPORT_PATH,
    export_transactions_csv,
    rebuild_cache,
    stats_context,
)

STOPWORDS = {
    "what",
    "where",
    "when",
    "which",
    "about",
    "show",
    "spend",
    "spent",
    "with",
    "from",
    "this",
    "that",
    "month",
    "months",
    "category",
    "categories",
}
MONTH_RE = re.compile(r"\b(20\d{2}-\d{2})\b")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive Ollama Q&A over categorized budget data.")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model to use (default: {DEFAULT_MODEL})")
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
    parser.add_argument("--rebuild", action="store_true", help="Rebuild the SQLite cache before starting")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db_path)
    crosswalk_path = Path(args.crosswalk)

    ensure_cache(db_path, args.csv_file, crosswalk_path, force_rebuild=args.rebuild)
    run_repl(db_path, args.csv_file, crosswalk_path, model=args.model)


def ensure_cache(
    db_path: Path,
    csv_file: str | None,
    crosswalk_path: Path,
    *,
    force_rebuild: bool,
) -> None:
    if force_rebuild or not db_path.exists():
        print("Building local SQLite cache from source CSV data...")
        inserted, skipped = rebuild_cache(db_path, csv_file, crosswalk_path)
        print(f"Cache ready: {inserted} row(s), {skipped} row(s) with unparseable date format.")


def run_repl(db_path: Path, csv_file: str | None, crosswalk_path: Path, *, model: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        print("\nInteractive data Q&A is ready.")
        print("Commands: :help  :stats  :rebuild  :export [path]  :income [YYYY-MM]  :topcats [YYYY-MM] [N]  :month YYYY-MM  :merchant NAME  :quit")

        while True:
            question = input("\nask> ").strip()
            if not question:
                continue

            outcome = handle_command(question, conn, db_path, csv_file, crosswalk_path)
            if outcome == "quit":
                print("Goodbye.")
                return
            if isinstance(outcome, sqlite3.Connection):
                conn = outcome
                continue
            if outcome == "handled":
                continue

            try:
                response = answer_question(conn, question, model)
            except Exception as exc:  # noqa: BLE001
                print(f"Error while generating answer: {exc}")
                continue

            print("\n" + response)
    finally:
        conn.close()


def handle_command(
    question: str,
    conn: sqlite3.Connection,
    db_path: Path,
    csv_file: str | None,
    crosswalk_path: Path,
) -> str | sqlite3.Connection:
    if question in {":quit", ":q", "quit", "exit"}:
        return "quit"

    if question == ":help":
        print_help()
        return "handled"

    if question.startswith(":export"):
        parts = question.split(maxsplit=1)
        output_path = Path(parts[1]) if len(parts) > 1 else DEFAULT_TRANSACTIONS_EXPORT_PATH
        count = export_transactions_csv(conn, output_path)
        print(f"Exported {count} row(s) to {output_path}")
        return "handled"

    if question.startswith(":income"):
        month = extract_month(question)
        print(deterministic_income_summary(conn, month) + "\n")
        return "handled"

    if question.startswith(":topcats"):
        month = extract_month(question)
        limit = extract_limit(question, default=5)
        print(deterministic_top_categories(conn, month, limit) + "\n")
        return "handled"

    if question.startswith(":month"):
        month = extract_month(question)
        if not month:
            print("Usage: :month YYYY-MM\n")
            return "handled"
        print(deterministic_month_breakdown(conn, month) + "\n")
        return "handled"

    if question.startswith(":merchant"):
        merchant = question.removeprefix(":merchant").strip()
        if not merchant:
            print("Usage: :merchant NAME\n")
            return "handled"
        month = extract_month(question)
        print(deterministic_merchant_summary(conn, merchant, month) + "\n")
        return "handled"

    if question == ":stats":
        print_stats(conn)
        return "handled"

    if question == ":rebuild":
        conn.close()
        inserted, skipped = rebuild_cache(db_path, csv_file, crosswalk_path)
        new_conn = sqlite3.connect(db_path)
        print(f"Cache rebuilt: {inserted} row(s), {skipped} row(s) with unparseable date format.")
        return new_conn

    return "unhandled"


def answer_question(conn: sqlite3.Connection, question: str, model: str) -> str:
    deterministic = deterministic_answer(conn, question)
    if deterministic is not None:
        return deterministic

    context = stats_context(conn)
    samples = sample_rows_for_question(conn, question)
    prompt = build_prompt(question, context, samples)
    return ollama_chat([{"role": "user", "content": prompt}], model)


def print_help() -> None:
    print(
        "\nAvailable commands:\n"
        "- :help\n"
        "- :stats\n"
        "- :rebuild\n"
        "- :export [path]\n"
        "- :income [YYYY-MM]\n"
        "- :topcats [YYYY-MM] [N]\n"
        "- :month YYYY-MM\n"
        "- :merchant NAME\n"
        "- :quit\n"
    )


def extract_month(text: str) -> str | None:
    match = MONTH_RE.search(text)
    return match.group(1) if match else None


def extract_limit(text: str, default: int = 5) -> int:
    nums = re.findall(r"\b\d+\b", text)
    if not nums:
        return default
    value = int(nums[-1])
    return max(1, min(value, 20))


def fmt_money(value: float) -> str:
    return f"${value:.2f}"


def deterministic_income_summary(conn: sqlite3.Connection, month: str | None) -> str:
    if month:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN c.name = 'Income' THEN t.amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN t.amount < 0 AND c.name != 'Transfer' THEN t.amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN c.name = 'Transfer' THEN t.amount ELSE 0 END), 0)
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE substr(t.posted_date, 1, 7) = ?
            """,
            (month,),
        ).fetchone()
        label = f"for {month}"
    else:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN c.name = 'Income' THEN t.amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN t.amount < 0 AND c.name != 'Transfer' THEN t.amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN c.name = 'Transfer' THEN t.amount ELSE 0 END), 0)
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            """
        ).fetchone()
        label = "across all data"

    income_total, expense_total, transfer_total = row
    net_total = income_total + expense_total
    return (
        f"Income and cash flow {label}:\n"
        f"- Income: {fmt_money(income_total)}\n"
        f"- Expenses (excl Transfer): {fmt_money(expense_total)}\n"
        f"- Net (Income + Expenses): {fmt_money(net_total)}\n"
        f"- Transfers: {fmt_money(transfer_total)}"
    )


def deterministic_top_categories(conn: sqlite3.Connection, month: str | None, limit: int) -> str:
    if month:
        rows = conn.execute(
            """
            SELECT c.name, SUM(t.amount) AS total
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE substr(t.posted_date, 1, 7) = ? AND t.amount < 0 AND c.name != 'Transfer'
            GROUP BY c.name
            ORDER BY total ASC
            LIMIT ?
            """,
            (month, limit),
        ).fetchall()
        title = f"Top expense categories for {month}"
    else:
        rows = conn.execute(
            """
            SELECT c.name, SUM(t.amount) AS total
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE t.amount < 0 AND c.name != 'Transfer'
            GROUP BY c.name
            ORDER BY total ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        title = "Top expense categories across all data"

    if not rows:
        return f"{title}: no data found."

    lines = [title + ":"]
    for category, total in rows:
        lines.append(f"- {category}: {fmt_money(total)}")
    return "\n".join(lines)


def deterministic_month_breakdown(conn: sqlite3.Connection, month: str) -> str:
    rows = conn.execute(
        """
        SELECT c.name, SUM(t.amount) AS total
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE substr(t.posted_date, 1, 7) = ?
        GROUP BY c.name
        ORDER BY total ASC
        """,
        (month,),
    ).fetchall()

    if not rows:
        return f"No rows found for {month}."

    lines = [f"Category totals for {month}:"]
    for category, total in rows:
        lines.append(f"- {category}: {fmt_money(total)}")
    return "\n".join(lines)


def deterministic_merchant_summary(conn: sqlite3.Connection, merchant: str, month: str | None) -> str:
    pattern = f"%{merchant.upper()}%"
    if month:
        rows = conn.execute(
            """
            SELECT t.merchant_normalized, SUM(t.amount) AS total, COUNT(*) AS txn_count
            FROM transactions t
            WHERE substr(t.posted_date, 1, 7) = ? AND t.merchant_normalized LIKE ?
            GROUP BY t.merchant_normalized
            ORDER BY ABS(total) DESC
            LIMIT 8
            """,
            (month, pattern),
        ).fetchall()
        title = f"Merchant match for '{merchant}' in {month}"
    else:
        rows = conn.execute(
            """
            SELECT t.merchant_normalized, SUM(t.amount) AS total, COUNT(*) AS txn_count
            FROM transactions t
            WHERE t.merchant_normalized LIKE ?
            GROUP BY t.merchant_normalized
            ORDER BY ABS(total) DESC
            LIMIT 8
            """,
            (pattern,),
        ).fetchall()
        title = f"Merchant match for '{merchant}'"

    if not rows:
        return f"{title}: no matching merchants found."

    lines = [title + ":"]
    for merchant_name, total, count in rows:
        lines.append(f"- {merchant_name}: {fmt_money(total)} across {count} transaction(s)")
    return "\n".join(lines)


def deterministic_category_summary(
    conn: sqlite3.Connection,
    category: str,
    month: str | None,
    *,
    average_monthly: bool = False,
    spending_context: bool = False,
) -> str:
    if month:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(t.amount), 0), COUNT(*)
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE substr(t.posted_date, 1, 7) = ? AND lower(c.name) = lower(?)
            """,
            (month, category),
        ).fetchone()
        total, count = row
        return f"{category} for {month}: {fmt_money(total)} across {count} transaction(s)."

    if average_monthly:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(t.amount), 0),
                COUNT(*),
                COUNT(DISTINCT substr(t.posted_date, 1, 7))
            FROM transactions t
            JOIN categories c ON c.id = t.category_id
            WHERE lower(c.name) = lower(?) AND t.posted_date IS NOT NULL AND t.posted_date != ''
            """,
            (category,),
        ).fetchone()
        total, count, active_months = row
        if not active_months:
            return f"No month-labeled rows found for category '{category}'."

        avg_monthly = total / active_months
        display_value = abs(avg_monthly) if spending_context and avg_monthly < 0 else avg_monthly
        return (
            f"{category} average per month: ${display_value:.2f} "
            f"across {active_months} month(s) and {count} transaction(s)."
        )

    row = conn.execute(
        """
        SELECT COALESCE(SUM(t.amount), 0), COUNT(*)
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE lower(c.name) = lower(?)
        """,
        (category,),
    ).fetchone()
    total, count = row
    return f"{category} across all data: {fmt_money(total)} across {count} transaction(s)."


def known_categories(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM categories ORDER BY name").fetchall()
    return [row[0] for row in rows if row and row[0]]


def deterministic_answer(conn: sqlite3.Connection, question: str) -> str | None:
    q = question.lower()
    month = extract_month(question)
    average_monthly = any(phrase in q for phrase in ("average", "avg", "per month", "monthly average"))
    spending_context = any(word in q for word in ("how much", "spent", "spend"))

    if any(word in q for word in ("income", "savings", "cash flow", "net")):
        return deterministic_income_summary(conn, month)

    if ("top" in q or "biggest" in q) and ("category" in q or "categories" in q):
        return deterministic_top_categories(conn, month, limit=5)

    if month and ("breakdown" in q or "by category" in q or "for month" in q):
        return deterministic_month_breakdown(conn, month)

    if "merchant" in q or "vendor" in q:
        m = re.search(r"(?:merchant|vendor)\s+(.+)$", question, flags=re.IGNORECASE)
        if m:
            merchant = m.group(1).strip()
            if merchant:
                return deterministic_merchant_summary(conn, merchant, month)

    categories = known_categories(conn)
    q_norm = re.sub(r"\s+", " ", q)
    for category in categories:
        if category.lower() in q_norm and ("how much" in q_norm or "spent" in q_norm or "spend" in q_norm):
            return deterministic_category_summary(
                conn,
                category,
                month,
                average_monthly=average_monthly,
                spending_context=spending_context,
            )

    return None


def build_prompt(
    question: str,
    context: str,
    samples: list[tuple[str, str, float, str]],
) -> str:
    sample_lines = ["Potentially relevant rows based on your question:"]
    if not samples:
        sample_lines.append("- (No direct row matches found by keyword filter)")
    else:
        for posted_date, category, amount, description in samples:
            sample_lines.append(f"- {posted_date} | {category} | ${amount:.2f} | {description}")

    return f"""You are a finance data assistant. Answer the user's question only using the provided dataset context.

Rules:
- If you do not have enough data in context, say exactly what is missing.
- Do not invent transactions or amounts.
- Keep answers concise and include key numbers.

User question:
{question}

{context}

{chr(10).join(sample_lines)}
"""


def print_stats(conn: sqlite3.Connection) -> None:
    print("\n" + stats_context(conn) + "\n")


def sample_rows_for_question(
    conn: sqlite3.Connection,
    question: str,
    limit: int = 25,
) -> list[tuple[str, str, float, str]]:
    tokens = [
        tok.upper()
        for tok in re.findall(r"[A-Za-z][A-Za-z0-9&'*.-]{2,}", question)
        if tok.lower() not in STOPWORDS
    ]
    tokens = list(dict.fromkeys(tokens))[:6]

    if not tokens:
        return []

    where = " OR ".join(
        "(t.merchant_normalized LIKE ? OR t.description LIKE ? OR c.name LIKE ? OR substr(t.posted_date, 1, 7) LIKE ?)"
        for _ in tokens
    )

    params: list[str] = []
    for token in tokens:
        pattern = f"%{token}%"
        params.extend([pattern, pattern, pattern, pattern])
    params.append(str(limit))

    query = f"""
        SELECT COALESCE(t.posted_date, ''), c.name, t.amount, t.description
        FROM transactions t
        JOIN categories c ON c.id = t.category_id
        WHERE {where}
        ORDER BY ABS(t.amount) DESC
        LIMIT ?
    """
    return conn.execute(query, params).fetchall()


if __name__ == "__main__":
    main()
