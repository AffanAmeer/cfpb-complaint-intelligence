"""
Export the star schema from the DuckDB warehouse into flat CSV files for Power BI.

Why this exists
    Power BI Desktop runs on the Windows lab machines, and the warehouse is a
    DuckDB file on the Mac. This script copies the star schema out as plain CSV
    files that Power BI can load with Power Query (Get Data > Text/CSV).

What it writes (to data/powerbi/, which is git-ignored because it is large)
    dim_date.csv      one row per day
    dim_product.csv   one row per product + sub-product, with product_group
    dim_issue.csv     one row per issue + sub-issue
    dim_company.csv   one row per company, with is_credit_bureau
    dim_state.csv     one row per state code
    fact_monthly.csv  complaints counted per month and every dimension key,
                      plus the flags needed for rates (timely, relief, closed)

Why monthly and not one row per complaint
    The fact table has about 19 million rows. Power BI can import that, but the
    file would be several gigabytes and slow to refresh. Counting per month and
    per dimension key keeps every number exact for counts and rates (a sum of
    counts is still the right count), and the file stays a manageable size.

How to run it on the Mac (from the project folder, with the venv active)
    python src/powerbi/export_for_powerbi.py
"""

import argparse
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = PROJECT_ROOT / "data" / "warehouse" / "complaints.duckdb"
OUT_DIR = PROJECT_ROOT / "data" / "powerbi"

# Each table to export: output file name, and the SQL that produces it.
EXPORTS = {
    "dim_date": "select * from marts.dim_date order by date_key",
    "dim_product": "select * from marts.dim_product order by product_key",
    "dim_issue": "select * from marts.dim_issue order by issue_key",
    "dim_company": "select * from marts.dim_company order by company_key",
    "dim_state": "select * from marts.dim_state order by state_code",
    # Monthly fact. Keys are kept (not names) so Power BI can use the relationships
    # in the star schema. The flags are counted as 0/1 so DAX can sum them.
    "fact_monthly": """
        select
            d.month_start                                  as month_start,
            f.company_key,
            f.product_key,
            f.issue_key,
            coalesce(f.state_code, '(none)')               as state_code,
            f.company_response,
            f.is_timely_response,
            f.is_in_progress,
            f.has_monetary_relief,
            f.is_servicemember,
            f.is_older_american,
            count(*)                                       as complaints
        from marts.fact_complaints as f
        join marts.dim_date as d
            on d.date_key = f.date_received_key
        group by all
        order by month_start, company_key, product_key, issue_key
    """,
}


def main():
    parser = argparse.ArgumentParser(description="Export the star schema to CSV for Power BI.")
    parser.add_argument("--db", default=str(DB_PATH), help="path to the DuckDB warehouse")
    parser.add_argument("--out", default=str(OUT_DIR), help="folder to write the CSV files to")
    args = parser.parse_args()

    if not Path(args.db).exists():
        raise SystemExit(f"No warehouse at {args.db}. Run the ingestion and dbt steps first.")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(args.db, read_only=True)

    # The reporting window (same rule as the SQL KPIs), so Power BI can hide incomplete months.
    window_sql = (PROJECT_ROOT / "sql" / "analysis" / "_window.sql").read_text()
    con.execute(window_sql)
    con.execute(f"copy (select * from analysis_window) to '{out_dir / 'reporting_window.csv'}' (header, delimiter ',')")
    print(f"reporting_window: 1 row -> {out_dir / 'reporting_window.csv'}")

    for name, sql in EXPORTS.items():
        out_path = out_dir / f"{name}.csv"
        con.execute(f"copy ({sql.strip()}) to '{out_path}' (header, delimiter ',')")
        rows = con.execute(f"select count(*) from ({sql.strip()})").fetchone()[0]
        print(f"{name}: {rows:,} rows -> {out_path}")

    con.close()


if __name__ == "__main__":
    main()
