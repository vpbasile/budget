#!/usr/bin/env python3
"""Report generation helpers for budget analysis."""

from __future__ import annotations

from budget_core import ollama_chat


def generate_budget_report(agg: dict, model: str) -> str:
    """Ask Ollama to interpret the aggregated data and suggest a budget."""
    summary_lines = ["Category spending totals across all months:"]
    for cat, total in sorted(agg["category_totals"].items(), key=lambda x: x[1]):
        summary_lines.append(f"  {cat}: ${total:.2f}")

    income_total = agg["category_totals"].get("Income", 0.0)
    transfer_total = agg["category_totals"].get("Transfer", 0.0)
    expense_total = sum(
        total
        for cat, total in agg["category_totals"].items()
        if total < 0 and cat != "Transfer"
    )
    net_total = income_total + expense_total

    summary_lines.append("\nComputed totals (for grounding):")
    summary_lines.append(f"  Income total: ${income_total:.2f}")
    summary_lines.append(f"  Expense total (excl Transfer): ${expense_total:.2f}")
    summary_lines.append(f"  Net (Income + Expenses): ${net_total:.2f}")
    summary_lines.append(f"  Transfer total: ${transfer_total:.2f}")

    monthly_lines = ["\nMonthly breakdown (category: $amount):"]
    for month, cats in agg["monthly"].items():
        monthly_lines.append(f"\n{month}:")
        for cat, amt in sorted(cats.items()):
            monthly_lines.append(f"  {cat}: ${amt:.2f}")

    data_summary = "\n".join(summary_lines + monthly_lines)

    prompt = f"""You are a personal finance analyst who wants to help give me transparency into my finances and spending habits. Based on the transaction data below, write a clear budget report that includes:

1. **Monthly Averages per category** — average monthly spend for every defined category (exclude Income/Transfer)
2. **Spending Overview** — with breakdowns of the top expense categories and notable patterns

Rules:
- If Income total is greater than $0, explicitly acknowledge that income was detected.
- Use Net (Income + Expenses) as the savings/cash-flow signal.

Keep the tone friendly and practical. Use markdown formatting.

{data_summary}"""

    messages = [{"role": "user", "content": prompt}]
    return ollama_chat(messages, model)
