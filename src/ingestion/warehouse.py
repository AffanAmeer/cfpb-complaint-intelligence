"""
Shared warehouse code for every loader: where the database lives, the raw
table definitions, and the one function that writes complaints into it.

Both loaders (load_bulk.py and load_api.py) go through merge_complaints(), so
there is exactly one place that decides how a complaint is inserted or updated.

The raw layer
    raw.complaints keeps the source values as they arrived. We only do the
    minimum typing needed to make it usable: complaint_id becomes a number,
    dates become real dates, and API timestamps become UTC timestamps.
    No cleaning (renamed products, messy company names) happens here. That is
    the job of the dbt models in Phase 3.

Dates and time zones
    The API sends timestamps like 2026-11-06T03:16:09.000Z. The Z means UTC.
    We store them as received_at_utc / sent_at_utc, and date_received is the
    UTC calendar day of that timestamp. The API's own date filter also uses
    UTC days (checked with scratch/probe_api.py on 2026-11-07).
    The bulk CSV only has a date (no clock time), so for bulk rows the
    *_at_utc columns stay empty until the API refreshes that complaint.
"""

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb

DB_PATH = Path("data/warehouse/complaints.duckdb")
LOG_PATH = Path("logs/ingestion.log")

COMPLAINT_COLUMNS = [
    "complaint_id",
    "date_received",
    "date_sent_to_company",
    "received_at_utc",
    "sent_at_utc",
    "product",
    "sub_product",
    "issue",
    "sub_issue",
    "company",
    "state",
    "zip_code",
    "tags",
    "submitted_via",
    "company_response",
    "company_public_response",
    "timely",
]

SCHEMA_SQL = """
CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.complaints (
    complaint_id            BIGINT PRIMARY KEY,
    date_received           DATE NOT NULL,
    date_sent_to_company    DATE,
    received_at_utc         TIMESTAMP,
    sent_at_utc             TIMESTAMP,
    product                 VARCHAR,
    sub_product             VARCHAR,
    issue                   VARCHAR,
    sub_issue               VARCHAR,
    company                 VARCHAR,
    state                   VARCHAR,
    zip_code                VARCHAR,
    tags                    VARCHAR,
    submitted_via           VARCHAR,
    company_response        VARCHAR,
    company_public_response VARCHAR,
    timely                  VARCHAR,
    source                  VARCHAR NOT NULL,
    source_as_of_utc        TIMESTAMP NOT NULL,
    first_loaded_at_utc     TIMESTAMP NOT NULL,
    last_loaded_at_utc      TIMESTAMP NOT NULL,
    last_run_id             VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS raw.load_log (
    run_id              VARCHAR PRIMARY KEY,
    source              VARCHAR,
    started_at_utc      TIMESTAMP,
    finished_at_utc     TIMESTAMP,
    source_as_of_utc    TIMESTAMP,
    rows_in_source      BIGINT,
    rows_inserted       BIGINT,
    rows_updated        BIGINT,
    rows_changed        BIGINT,
    rows_skipped_older  BIGINT,
    table_rows_after    BIGINT,
    notes               VARCHAR
);

CREATE TABLE IF NOT EXISTS raw.reconciliation_log (
    checked_at_utc  TIMESTAMP,
    check_name      VARCHAR,
    status          VARCHAR,
    warehouse_value BIGINT,
    source_value    BIGINT,
    difference      BIGINT,
    details         VARCHAR
);
"""


def utc_now():
    """Current time in UTC, without a time zone label (we store all times as UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_run_id():
    return uuid.uuid4().hex[:12]


def setup_logging():
    """Log to the screen and to logs/ingestion.log, so every run leaves a record."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    logging.Formatter.converter = time.gmtime
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)sZ %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(LOG_PATH)],
    )
    return logging.getLogger("ingestion")


def connect():
    """Open (or create) the DuckDB file and make sure the raw tables exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH))
    con.execute(SCHEMA_SQL)
    return con


def merge_complaints(con, staged_table, source, source_as_of_utc, run_id):
    """
    Upsert every row of `staged_table` into raw.complaints, keyed on complaint_id.

    `staged_table` must have the COMPLAINT_COLUMNS, already typed, with at most
    one row per complaint_id.

    - New complaint_id      -> INSERT it.
    - Existing complaint_id -> UPDATE it, but only if this data is at least as
      new as what we already stored (source_as_of_utc). That stops an old bulk
      file from overwriting fresher API data if we ever re-run the backfill.
    - A bulk row has no clock times, so it never wipes out API timestamps
      (COALESCE keeps the old value when the new one is empty).

    Returns a dict of counts: inserted, updated, changed, skipped_older. Running the same load twice
    gives the same table, which is what makes the load idempotent.
    """
    params = {"as_of": source_as_of_utc, "source": source, "now": utc_now(), "run_id": run_id}

    # Count what the MERGE is about to do, so the load log can say exactly
    # how many rows were new, refreshed, really changed, or skipped.
    # "changed" = an updated row where at least one business column is different
    # (for example "In progress" became "Closed with explanation").
    business = [c for c in COMPLAINT_COLUMNS if c not in ("complaint_id", "received_at_utc", "sent_at_utc")]
    new_values = ", ".join(f"s.{c}" for c in business)
    old_values = ", ".join(f"t.{c}" for c in business)
    inserted, updated, changed, skipped = con.execute(
        f"""
        SELECT
            count(*) FILTER (WHERE t.complaint_id IS NULL),
            count(*) FILTER (WHERE t.source_as_of_utc <= $as_of),
            count(*) FILTER (WHERE t.source_as_of_utc <= $as_of
                             AND ROW({new_values}) IS DISTINCT FROM ROW({old_values})),
            count(*) FILTER (WHERE t.source_as_of_utc > $as_of)
        FROM {staged_table} AS s
        LEFT JOIN raw.complaints AS t ON t.complaint_id = s.complaint_id
        """,
        {"as_of": source_as_of_utc},
    ).fetchone()

    updates = ",\n            ".join(f"{col} = s.{col}" for col in business)
    insert_cols = ", ".join(COMPLAINT_COLUMNS)
    insert_vals = ", ".join(f"s.{col}" for col in COMPLAINT_COLUMNS)

    con.execute(
        f"""
        MERGE INTO raw.complaints AS t
        USING {staged_table} AS s
        ON t.complaint_id = s.complaint_id
        WHEN MATCHED AND t.source_as_of_utc <= $as_of THEN UPDATE SET
            {updates},
            received_at_utc = COALESCE(s.received_at_utc, t.received_at_utc),
            sent_at_utc = COALESCE(s.sent_at_utc, t.sent_at_utc),
            source = $source,
            source_as_of_utc = $as_of,
            last_loaded_at_utc = $now,
            last_run_id = $run_id
        WHEN NOT MATCHED THEN INSERT
            ({insert_cols}, source, source_as_of_utc,
             first_loaded_at_utc, last_loaded_at_utc, last_run_id)
            VALUES ({insert_vals}, $source, $as_of, $now, $now, $run_id)
        """,
        params,
    )
    return {"inserted": inserted, "updated": updated, "changed": changed, "skipped_older": skipped}


def write_load_log(con, row):
    con.execute(
        """
        INSERT INTO raw.load_log VALUES (
            $run_id, $source, $started_at_utc, $finished_at_utc, $source_as_of_utc,
            $rows_in_source, $rows_inserted, $rows_updated, $rows_changed, $rows_skipped_older,
            $table_rows_after, $notes)
        """,
        row,
    )
