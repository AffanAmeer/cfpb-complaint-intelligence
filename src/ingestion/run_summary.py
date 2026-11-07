"""
Run summary: a short report of what one pipeline run did.

GitHub Actions shows a "summary" page for every run. Anything a step writes to
the file named in $GITHUB_STEP_SUMMARY appears there as Markdown. This script
prints that Markdown, so the workflow can do:

    python src/ingestion/run_summary.py --since "$STARTED_AT" >> "$GITHUB_STEP_SUMMARY"

It only reads the warehouse (read_only=True), so it can never change data.
It reads the logs the loaders already write (raw.load_log and
raw.reconciliation_log), keeping only rows from this run (--since).

How to run it on the Mac (from the project folder, with the venv active)
    python src/ingestion/run_summary.py --since 2026-11-07T00:00:00
"""

import argparse

import duckdb

from warehouse import DB_PATH


def table(headers, rows):
    """Turn rows into a Markdown table."""
    lines = ["| " + " | ".join(headers) + " |", "|" + " --- |" * len(headers)]
    for row in rows:
        lines.append("| " + " | ".join("" if v is None else f"{v:,}" if isinstance(v, int) else str(v)
                                       for v in row) + " |")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Markdown summary of one pipeline run.")
    parser.add_argument("--since", required=True, help="UTC start time of the run, YYYY-MM-DDTHH:MM:SS")
    args = parser.parse_args()

    print("## Pipeline run summary\n")
    if not DB_PATH.exists():
        print("No warehouse file on this runner, so the run stopped before loading anything.")
        return

    con = duckdb.connect(str(DB_PATH), read_only=True)
    rows, oldest, newest = con.execute(
        "SELECT count(*), min(date_received), max(date_received) FROM raw.complaints"
    ).fetchone()
    print(f"Warehouse: **{rows:,} complaints**, {oldest} to {newest}.\n")

    loads = con.execute(
        """
        SELECT source, notes, rows_in_source, rows_inserted, rows_updated, rows_changed
        FROM raw.load_log
        WHERE started_at_utc >= CAST($since AS TIMESTAMP)
        ORDER BY started_at_utc
        """,
        {"since": args.since},
    ).fetchall()
    print("### Loads in this run\n")
    print(table(["Source", "Notes", "Fetched", "New", "Refreshed", "Changed"], loads)
          if loads else "No loads ran.")

    checks = con.execute(
        """
        SELECT check_name, status, warehouse_value, source_value, details
        FROM raw.reconciliation_log
        WHERE checked_at_utc >= CAST($since AS TIMESTAMP)
        ORDER BY checked_at_utc
        """,
        {"since": args.since},
    ).fetchall()
    print("\n### Reconciliation\n")
    print(table(["Check", "Status", "Warehouse", "CFPB API", "Details"], checks)
          if checks else "Reconciliation did not run.")

    try:
        fact_rows = con.execute("SELECT count(*) FROM marts.fact_complaints").fetchone()[0]
        print(f"\n### Star schema\n\n`marts.fact_complaints` has {fact_rows:,} rows.")
    except duckdb.Error:
        print("\n### Star schema\n\nThe marts were not built in this run.")
    con.close()


if __name__ == "__main__":
    main()
