"""
Incremental load: pull recent complaints from the CFPB API and upsert them.

Why incremental
    The bulk backfill (load_bulk.py) gives us all history once. After that we
    only need what is new or changed, so each run asks the API for a short
    window of recent days instead of everything again.

Why a lookback window
    Complaints change after they are filed: "In progress" becomes "Closed
    with explanation" when the company replies, which can take a couple of
    weeks. So each run re-pulls the last LOOKBACK_DAYS days, not just the
    newest day, and the upsert overwrites those rows with the fresh values.
    A longer lookback catches more changes but costs more requests (about
    150 to 350 requests per day of complaints). Older changes are picked up
    whenever we re-run the bulk backfill.

How paging works
    The API gives at most 100 rows per request. We sort newest first and,
    for the next page, pass search_after = "<timestamp>_<complaint_id>" from
    the last row of the previous page (tested in scratch/probe_api.py).
    The complaint ID is a tie-breaker, so two complaints with the same
    timestamp can never be skipped or repeated.

Built-in check
    For every day, the rows we fetched must equal the API's own count for that
    day. If they don't, the day is logged as a warning in raw.load_log.

How to run it (from the project folder, with the venv active)
    python src/ingestion/load_api.py                 newest day we hold minus 7 days, up to today
    python src/ingestion/load_api.py --days 1        only the newest day we hold (a quick test)
    python src/ingestion/load_api.py --start 2026-11-01 --end 2026-11-03
All dates are UTC days.
"""

import argparse
import time
from datetime import date, datetime, timedelta, timezone

import pandas as pd
import requests

from warehouse import (
    COMPLAINT_COLUMNS,
    connect,
    merge_complaints,
    new_run_id,
    setup_logging,
    utc_now,
    write_load_log,
)

BASE_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
PAGE_SIZE = 100
MAX_TRIES = 5
PAUSE_SECONDS = 0.2
LOOKBACK_DAYS = 7

API_FIELDS = [
    "complaint_id", "date_received", "date_sent_to_company", "product", "sub_product",
    "issue", "sub_issue", "company", "state", "zip_code", "tags", "submitted_via",
    "company_response", "company_public_response", "timely",
]


def get_with_retries(params, log):
    """GET the API, retrying with exponential backoff (2s, 4s, 8s, 16s) on failure."""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            response = requests.get(BASE_URL, params=params, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            if attempt == MAX_TRIES:
                raise
            wait = 2 ** attempt
            log.warning("Attempt %s failed (%s); retrying in %ss", attempt, error, wait)
            time.sleep(wait)


def fetch_day(day, log):
    """Fetch every complaint received on one UTC day. Returns (records, api_count, as_of_utc)."""
    base = {
        "date_received_min": day.isoformat(),
        "date_received_max": day.isoformat(),
        "sort": "created_date_desc",
        "size": PAGE_SIZE,
        "no_aggs": "true",
    }
    records = []
    cursor = None
    api_count = None
    as_of_utc = None
    while True:
        params = dict(base)
        if cursor:
            params["search_after"] = cursor
        data = get_with_retries(params, log)
        if api_count is None:
            api_count = data["hits"]["total"]["value"]
            last_indexed = datetime.fromisoformat(data["_meta"]["last_indexed"])
            as_of_utc = last_indexed.astimezone(timezone.utc).replace(tzinfo=None)
        hits = data["hits"]["hits"]
        if not hits:
            break
        records.extend(hit["_source"] for hit in hits)
        last_sort = hits[-1]["sort"]
        cursor = f"{last_sort[0]}_{last_sort[1]}"
        if len(hits) < PAGE_SIZE:
            break
        time.sleep(PAUSE_SECONDS)
    return records, api_count, as_of_utc


def stage_records(con, records):
    """Put the API records in a temp table with real types (UTC timestamps, dates, numbers)."""
    frame = pd.DataFrame(records).reindex(columns=API_FIELDS).astype("string")
    con.register("api_records", frame)
    other_cols = [c for c in COMPLAINT_COLUMNS
                  if c not in ("complaint_id", "date_received", "date_sent_to_company",
                               "received_at_utc", "sent_at_utc")]
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE api_stage AS
        WITH typed AS (
            SELECT
                CAST(complaint_id AS BIGINT)                                AS complaint_id,
                CAST(replace(date_received, 'Z', '') AS TIMESTAMP)          AS received_at_utc,
                CAST(replace(date_sent_to_company, 'Z', '') AS TIMESTAMP)   AS sent_at_utc,
                {", ".join(other_cols)}
            FROM api_records
        )
        SELECT
            complaint_id,
            CAST(received_at_utc AS DATE) AS date_received,
            CAST(sent_at_utc AS DATE)     AS date_sent_to_company,
            received_at_utc,
            sent_at_utc,
            {", ".join(other_cols)}
        FROM typed
        QUALIFY row_number() OVER (PARTITION BY complaint_id ORDER BY received_at_utc DESC) = 1
        """
    )
    con.unregister("api_records")


def pick_days(con, args):
    """Work out which UTC days to load from the command-line options."""
    today = datetime.now(timezone.utc).date()
    if args.start:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else today
    else:
        newest = con.execute("SELECT max(date_received) FROM raw.complaints").fetchone()[0]
        if newest is None:
            raise SystemExit("raw.complaints is empty. Run load_bulk.py first, or pass --start.")
        if args.days:
            start = newest - timedelta(days=args.days - 1)
            end = date.fromisoformat(args.end) if args.end else newest
        else:
            start = newest - timedelta(days=LOOKBACK_DAYS)
            end = date.fromisoformat(args.end) if args.end else today
    if start > end:
        raise SystemExit(f"Start {start} is after end {end}.")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def main():
    parser = argparse.ArgumentParser(description="Incremental load of recent CFPB complaints.")
    parser.add_argument("--start", help="first UTC day to load, YYYY-MM-DD")
    parser.add_argument("--end", help="last UTC day to load, YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, help="load this many days ending at the newest day we hold")
    args = parser.parse_args()

    log = setup_logging()
    run_id = new_run_id()
    con = connect()
    days = pick_days(con, args)
    log.info("API run %s: loading %s UTC days, %s to %s", run_id, len(days), days[0], days[-1])

    totals = {"fetched": 0, "inserted": 0, "updated": 0, "changed": 0, "skipped_older": 0}
    mismatched_days = []
    for day in days:
        started = utc_now()
        records, api_count, as_of_utc = fetch_day(day, log)
        note = "ok"
        if len(records) != api_count:
            note = f"fetched {len(records)} but API count is {api_count}"
            mismatched_days.append(day)
            log.warning("%s: %s", day, note)

        counts = {"inserted": 0, "updated": 0, "changed": 0, "skipped_older": 0}
        con.execute("BEGIN TRANSACTION")
        if records:
            stage_records(con, records)
            counts = merge_complaints(con, "api_stage", "api", as_of_utc, run_id)
        table_rows = con.execute("SELECT count(*) FROM raw.complaints").fetchone()[0]
        write_load_log(con, {
            "run_id": f"{run_id}-{day.isoformat()}",
            "source": "api",
            "started_at_utc": started,
            "finished_at_utc": utc_now(),
            "source_as_of_utc": as_of_utc,
            "rows_in_source": len(records),
            "rows_inserted": counts["inserted"],
            "rows_updated": counts["updated"],
            "rows_changed": counts["changed"],
            "rows_skipped_older": counts["skipped_older"],
            "table_rows_after": table_rows,
            "notes": f"day {day.isoformat()}: {note}",
        })
        con.execute("COMMIT")

        totals["fetched"] += len(records)
        for key in counts:
            totals[key] += counts[key]
        log.info(
            "%s: %s fetched (API says %s) | %s new, %s refreshed, %s changed, %s skipped",
            day, f"{len(records):,}", f"{api_count:,}", f"{counts['inserted']:,}",
            f"{counts['updated']:,}", f"{counts['changed']:,}", f"{counts['skipped_older']:,}",
        )

    con.execute("CHECKPOINT")
    con.close()
    log.info(
        "Done: %s fetched, %s new, %s refreshed (%s changed), %s skipped. Days with a count mismatch: %s",
        f"{totals['fetched']:,}", f"{totals['inserted']:,}", f"{totals['updated']:,}",
        f"{totals['changed']:,}", f"{totals['skipped_older']:,}",
        [d.isoformat() for d in mismatched_days] or "none",
    )


if __name__ == "__main__":
    main()
