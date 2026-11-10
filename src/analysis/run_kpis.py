"""
Run every KPI query in sql/analysis/ and save each result as a CSV in reports/kpis/.

How it works
    1. Open the warehouse read-only (a report can never change the data).
    2. Run sql/analysis/_window.sql, which creates a temporary view called
       analysis_window: the as-of date and the "complete months" to report on.
    3. Run each numbered query (00_..., 01_..., in order), save it as
       reports/kpis/<same name>.csv, and print the first rows.

The SQL lives in .sql files, not in this script, so each query can be read,
reviewed and reused on its own (Power BI, Databricks). Python is only the runner.

How to run it on the Mac (from the project folder, with the venv active)
    python src/analysis/run_kpis.py
    python src/analysis/run_kpis.py --only 04     (just one query)
"""

import argparse
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "complaints.duckdb"
SQL_DIR = PROJECT_ROOT / "sql" / "analysis"
OUT_DIR = PROJECT_ROOT / "reports" / "kpis"


def main():
    parser = argparse.ArgumentParser(description="Run the KPI queries and save CSVs.")
    parser.add_argument("--db", default=str(DB_PATH), help="path to the DuckDB warehouse")
    parser.add_argument("--only", help="run only queries whose file name starts with this, e.g. 04")
    args = parser.parse_args()

    if not Path(args.db).exists():
        raise SystemExit(f"No warehouse at {args.db}. Run the ingestion and dbt steps first.")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db, read_only=True)

    con.execute((SQL_DIR / "_window.sql").read_text())
    window = con.sql("select * from analysis_window").df().iloc[0]
    print(f"Data as of {window.as_of_date:%Y-%m-%d}. "
          f"Current 12 months: {window.current_start:%Y-%m-%d} to {window.last_month_end:%Y-%m-%d}. "
          f"Prior 12 months: {window.prior_start:%Y-%m-%d} to {window.prior_end:%Y-%m-%d}.\n")

    queries = sorted(p for p in SQL_DIR.glob("[0-9]*.sql"))
    if args.only:
        queries = [p for p in queries if p.name.startswith(args.only)]

    pd.set_option("display.width", 200)
    pd.set_option("display.max_columns", 20)
    for path in queries:
        result = con.sql(path.read_text()).df()
        out_path = OUT_DIR / f"{path.stem}.csv"
        result.to_csv(out_path, index=False)
        print(f"== {path.name}: {len(result):,} rows -> {out_path.relative_to(PROJECT_ROOT)}")
        print(result.head(12).to_string(index=False))
        print()

    con.close()


if __name__ == "__main__":
    main()
