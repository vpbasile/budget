# TODO

## Top-Down Refactor Checklist

1. Define the canonical transaction contract.
- Fields: source_file, source_row, posted_date, month, description_raw, merchant_normalized, amount, category, matched_rule.
- Keep the contract stable for batch reporting and interactive Q&A.

2. Extract pure domain logic from `budget_analyzer.py`.
- Move parsing, merchant normalization, crosswalk matching, and aggregation into a new `budget_core.py`.
- Keep these functions free of CLI, file paths, and Ollama calls.

3. Separate data access from domain logic.
- Add `budget_storage.py` for CSV loading and SQLite cache writes/reads.
- Keep `interactive_qa.py` focused on query flow rather than data preparation.

4. Split reporting from analysis.
- Move Ollama prompt assembly and report generation into a dedicated `budget_reporting.py`.
- Keep numeric summaries computed deterministically before the LLM sees any context.

5. Rebuild the workflow scripts around the shared core.
- Keep `budget_analyzer.py` as the batch workflow entry point.
- Keep `interactive_qa.py` as the conversational workflow entry point.
- Keep `strip_category_column.py` and `crosswalk_sync.py` as narrow utility scripts.

6. Thin out `main.py`.
- Keep only menu routing and subprocess launching in `main.py`.
- Do not add business logic there.

7. Add contract-level tests.
- CSV parsing fixtures.
- Crosswalk matching fixtures.
- Aggregation fixtures.
- SQLite cache rebuild fixture.
- Q&A command fixtures once slash-commands exist.

8. Refactor in this execution order.
- Step 1: create `budget_core.py`.
- Step 2: update `budget_analyzer.py` to import from `budget_core.py`.
- Step 3: update `interactive_qa.py` to use shared core/storage helpers.
- Step 4: create `budget_reporting.py` and move prompt generation there.
- Step 5: add tests.

## Interactive Q&A Enhancements

- Add deterministic slash-commands to interactive_qa.py so common answers come from exact SQL.
- Implement :income to show total income, total expenses (excluding Transfer), transfer total, and net cash flow.
- Implement :topcats to show top spending categories for a selectable period.
- Implement :month YYYY-MM to show category totals and top merchants for that month.
- Implement :merchant <name> to show total spend, monthly trend, and sample rows for a merchant.
- Implement :category <name> to show totals and monthly trend for a category.
- Add lightweight help text (:help) listing all commands and expected formats.
- Keep LLM freeform Q&A for non-command input, but prefer deterministic responses when command syntax is used.
