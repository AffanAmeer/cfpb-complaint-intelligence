"""
Backfill: load the full complaint history from CFPB's bulk CSV into DuckDB.

Why a bulk file
    The API returns at most 100 complaints per request, so loading all ~19
    million through it would take about 190,000 requests. CFPB also publishes
    the whole database as one zipped CSV (about 350 MB zipped, 5.7 GB
    unzipped). We load that once, then load_api.py keeps it up to date.

What this script does
    1. Unzips complaints.csv next to the zip (skipped if it is already there).
    2. Reads the CSV with DuckDB, everything as text first, then casts the
       types itself, so nothing is guessed silently.
    3. Checks the file before loading: row count, duplicate complaint IDs,
       dates that would not parse.
    4. Upserts the rows into raw.complaints through warehouse.merge_complaints.
    5. Writes a row to raw.load_log and deletes the unzipped CSV.

The "as of" time
    Each row remembers how fresh its data is (source_as_of_utc). For the bulk
    file that is the time stored inside the zip for complaints.csv. CFPB is in
    Washington, so we read that time as US Eastern and convert it to UTC.

How to run it (from the project folder, with the venv active)
    curl -L -o data/raw/complaints.csv.zip https://files.consumerfinance.gov/ccdb/complaints.csv.zip
    python src/ingestion/load_bulk.py
Re-running it is safe: rows already up to date are refreshed in place, never
duplicated.
"""

import argparse
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from warehouse import (
    COMPLAINT_COLUMNS,
    connect,
    merge_complaints,
    new_run_id,
    setup_logging,
    utc_now,
    write_load_log,
)

DEFAULT_ZIP = Path("data/raw/complaints.csv.zip")
CSV_NAME = "complaints.csv"

COLUMN_MAP = {
    "Complaint ID": "complaint_id",
    "Date received": "date_received",
    "Date sent to company": "date_sent_to_company",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Sub-issue": "sub_issue",
    "Company": "company",
    "State": "state",
    "ZIP code": "zip_code",
    "Tags": "tags",
    "Submitted via": "submitted_via",
    "Company response to consumer": "company_response",
    "Company public response": "company_public_response",
    "Timely response?": "timely",
}


def unzip_csv(zip_path, log):
    """Extract complaints.csv and return its path plus the file's own timestamp in UTC."""
    with zipfile.ZipFile(zip_path) as archive:
        info = archive.getinfo(CSV_NAME)
        as_of_eastern = datetime(*info.date_time, tzinfo=ZoneInfo("America/New_York"))
        as_of_utc = as_of_eastern.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        csv_path = zip_path.parent / CSV_NAME
        if csv_path.exists() and csv_path.stat().st_size == info.file_size:
            log.info("Already unzipped: %s", csv_path)
        else:
            log.info("Unzipping %s (%.1f GB), this takes a minute or two...", CSV_NAME, info.file_size / 1e9)
            archive.extract(info, zip_path.parent)
    return csv_path, as_of_utc


def stage_csv(con, csv_path):
    """
    Read the CSV into one staging table with our column names and real types.

    The two views are just saved queries (nothing is copied). Only
    staging.bulk_typed is written, and it lives in the database file on disk,
    not in memory, so a 5.7 GB CSV doesn't need 5.7 GB of RAM.
    """
    con.execute("CREATE SCHEMA IF NOT EXISTS staging")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW bulk_text AS
        SELECT * FROM read_csv('{csv_path}', header = true, all_varchar = true)
        """
    )
    missing = set(COLUMN_MAP) - {row[0] for row in con.execute("DESCRIBE bulk_text").fetchall()}
    if missing:
        raise ValueError(f"The CSV is missing expected columns: {sorted(missing)}")

    renamed = ",\n            ".join(f'"{src}" AS {dst}' for src, dst in COLUMN_MAP.items())
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW bulk_named AS
        SELECT {renamed} FROM bulk_text
        """
    )

    text_cols = [c for c in COMPLAINT_COLUMNS
                 if c not in ("complaint_id", "date_received", "date_sent_to_company",
                              "received_at_utc", "sent_at_utc")]
    con.execute(
        f"""
        CREATE OR REPLACE TABLE staging.bulk_typed AS
        SELECT
            CAST(complaint_id AS BIGINT)                 AS complaint_id,
            TRY_CAST(date_received AS DATE)              AS date_received,
            TRY_CAST(date_sent_to_company AS DATE)       AS date_sent_to_company,
            CAST(NULL AS TIMESTAMP)                      AS received_at_utc,
            CAST(NULL AS TIMESTAMP)                      AS sent_at_utc,
            {", ".join(text_cols)},
            date_received        AS date_received_text,
            date_sent_to_company AS date_sent_text
        FROM bulk_named
        """
    )


def profile_stage(con):
    """The checks we run on the file BEFORE it touches the warehouse."""
    return dict(zip(
        ["rows", "distinct_ids", "bad_date_received", "bad_date_sent", "min_date", "max_date"],
        con.execute(
            """
            SELECT
                count(*),
                count(DISTINCT complaint_id),
                count(*) FILTER (WHERE date_received IS NULL),
                count(*) FILTER (WHERE date_sent_to_company IS NULL AND date_sent_text IS NOT NULL),
                min(date_received),
                max(date_received)
            FROM staging.bulk_typed
            """
        ).fetchone(),
    ))


def main():
    parser = argparse.ArgumentParser(description="Backfill raw.complaints from the CFPB bulk CSV.")
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP, help="path to complaints.csv.zip")
    parser.add_argument("--keep-csv", action="store_true", help="don't delete the unzipped CSV afterwards")
    args = parser.parse_args()

    log = setup_logging()
    run_id = new_run_id()
    started = utc_now()
    log.info("Bulk backfill run %s starting", run_id)

    csv_path, as_of_utc = unzip_csv(args.zip, log)
    log.info("Bulk file is as of %s UTC", as_of_utc)

    con = connect()
    stage_csv(con, csv_path)
    profile = profile_stage(con)
    log.info(
        "File check: %s rows, %s distinct complaint IDs, dates %s to %s",
        f"{profile['rows']:,}", f"{profile['distinct_ids']:,}", profile["min_date"], profile["max_date"],
    )
    log.info(
        "Unparseable dates: %s date_received, %s date_sent_to_company",
        profile["bad_date_received"], profile["bad_date_sent"],
    )
    if profile["bad_date_received"] > 0:
        raise ValueError("Some rows have no valid date_received. Stopping before loading anything.")

    duplicates = profile["rows"] - profile["distinct_ids"]
    if duplicates:
        log.warning("%s rows repeat a complaint ID; keeping one row per ID", f"{duplicates:,}")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW bulk_stage AS
        SELECT {", ".join(COMPLAINT_COLUMNS)}
        FROM staging.bulk_typed
        QUALIFY row_number() OVER (PARTITION BY complaint_id ORDER BY date_received DESC) = 1
        """
    )

    log.info("Merging into raw.complaints...")
    con.execute("BEGIN TRANSACTION")
    counts = merge_complaints(con, "bulk_stage", "bulk", as_of_utc, run_id)
    table_rows = con.execute("SELECT count(*) FROM raw.complaints").fetchone()[0]
    write_load_log(con, {
        "run_id": run_id,
        "source": "bulk",
        "started_at_utc": started,
        "finished_at_utc": utc_now(),
        "source_as_of_utc": as_of_utc,
        "rows_in_source": profile["rows"],
        "rows_inserted": counts["inserted"],
        "rows_updated": counts["updated"],
        "rows_changed": counts["changed"],
        "rows_skipped_older": counts["skipped_older"],
        "table_rows_after": table_rows,
        "notes": f"{duplicates} duplicate IDs in file; dates {profile['min_date']} to {profile['max_date']}",
    })
    con.execute("COMMIT")
    con.execute("DROP TABLE staging.bulk_typed")
    con.execute("CHECKPOINT")
    con.close()

    log.info(
        "Done: %s inserted, %s updated (%s actually changed), %s skipped as older. Table now has %s rows.",
        f"{counts['inserted']:,}", f"{counts['updated']:,}", f"{counts['changed']:,}",
        f"{counts['skipped_older']:,}", f"{table_rows:,}",
    )

    if not args.keep_csv:
        csv_path.unlink()
        log.info("Deleted the unzipped CSV (the zip is kept)")


if __name__ == "__main__":
    main()
