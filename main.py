from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_script(script_name: str, args: list[str] | None = None) -> None:
    args = args or []
    script_path = ROOT / script_name
    if not script_path.exists():
        print(f"\nScript not found: {script_path}\n")
        return

    cmd = [sys.executable, str(script_path), *args]
    print("\nRunning:", " ".join(shlex.quote(part) for part in cmd), "\n")

    try:
        completed = subprocess.run(cmd, cwd=ROOT, check=False)
    except KeyboardInterrupt:
        print("\nCancelled.\n")
        return

    if completed.returncode == 0:
        print("\nDone.\n")
    else:
        print(f"\nScript exited with code {completed.returncode}.\n")


def prompt(text: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{text}{suffix}: ").strip()
    if not value and default is not None:
        return default
    return value


def run_budget_analyzer_menu() -> None:
    print("\nBudget analyzer options")
    use_defaults = prompt("Use all defaults", "y").lower() in {"y", "yes"}
    if use_defaults:
        run_script("budget_analyzer.py")
        return

    args: list[str] = []

    db_path = prompt("SQLite DB path", "data/budget_qa.db")
    if db_path:
        args.extend(["--db-path", db_path])

    csv_file = prompt("Source CSV file(s), comma-separated", "")
    if csv_file:
        args.extend(["--csv-file", csv_file])

    crosswalk = prompt("Crosswalk path", "data/merchant_crosswalk.md")
    if crosswalk:
        args.extend(["--crosswalk", crosswalk])

    rebuild = prompt("Rebuild DB before analysis", "n").lower() in {"y", "yes"}
    if rebuild:
        args.append("--rebuild")

    model = prompt("Model", "llama3.2")
    if model:
        args.extend(["--model", model])

    output = prompt("Output report path", "data/budget_report.md")
    if output:
        args.extend(["--output", output])

    unmatched = prompt("Unmatched merchant report path", "data/unmatched_merchants_report.csv")
    if unmatched:
        args.extend(["--unmatched-report", unmatched])

    unmatched_min = prompt("Unmatched minimum count", "1")
    if unmatched_min:
        args.extend(["--unmatched-min-count", unmatched_min])

    run_script("budget_analyzer.py", args)


def run_interactive_qa_menu() -> None:
    print("\nInteractive data Q&A options")
    use_defaults = prompt("Use defaults", "y").lower() in {"y", "yes"}
    if use_defaults:
        run_script("interactive_qa.py", ["--rebuild"])
        return

    args: list[str] = []
    model = prompt("Model", "llama3.2")
    if model:
        args.extend(["--model", model])

    db_path = prompt("SQLite DB path", "data/budget_qa.db")
    if db_path:
        args.extend(["--db-path", db_path])

    csv_file = prompt("Source CSV file(s), comma-separated", "")
    if csv_file:
        args.extend(["--csv-file", csv_file])

    crosswalk = prompt("Crosswalk path", "data/merchant_crosswalk.md")
    if crosswalk:
        args.extend(["--crosswalk", crosswalk])

    rebuild = prompt("Rebuild cache now", "y").lower() in {"y", "yes"}
    if rebuild:
        args.append("--rebuild")

    run_script("interactive_qa.py", args)


def run_build_sqlite_db_menu() -> None:
    print("\nBuild SQLite DB options")
    use_defaults = prompt("Use defaults", "y").lower() in {"y", "yes"}
    if use_defaults:
        run_script("build_sqlite_db.py")
        return

    args: list[str] = []

    db_path = prompt("SQLite DB path", "data/budget_qa.db")
    if db_path:
        args.extend(["--db-path", db_path])

    csv_file = prompt("Source CSV file(s), comma-separated", "")
    if csv_file:
        args.extend(["--csv-file", csv_file])

    crosswalk = prompt("Crosswalk path", "data/merchant_crosswalk.md")
    if crosswalk:
        args.extend(["--crosswalk", crosswalk])

    run_script("build_sqlite_db.py", args)


def show_menu() -> None:
    print("Budget App Entry Point")
    print("=" * 24)
    print("1) Build SQLite DB")
    print("2) Analyze SQLite DB")
    print("3) Interactive data Q&A (Ollama)")
    print("4) Exit")


def main() -> None:
    while True:
        show_menu()
        choice = input("\nSelect an option: ").strip()

        if choice == "1":
            run_build_sqlite_db_menu()
        elif choice == "2":
            run_budget_analyzer_menu()
        elif choice == "3":
            run_interactive_qa_menu()
        elif choice == "4":
            print("Goodbye.")
            return
        else:
            print("\nInvalid selection. Please choose 1-4.\n")


if __name__ == "__main__":
    main()
