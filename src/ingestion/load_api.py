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
    150 to 350 requests per day of complaints). Older changes, and complaints
    CFPB publishes late for older days, are picked up by the daily bulk merge
    (load_bulk.py), which runs before this script.

How paging works
    The API gives at most 100 rows per request. We sort newest first and,
    for the next page, pass search_after = "<timestamp>_<complaint_id>" from
    the last row of the previous page (tested in scratch/probe_api.py).
    The complaint ID is a tie-breaker, so two complaints with the same
    timestamp can never be skipped or repeated.

Built-in check
    For every day, the rows we fetched must equal the API's own count for that
    day. If they don't, the day is logged as a warning in raw.load_log.

Removed complaints
    CFPB sometimes takes a complaint out after publishing it. When a day's
    fetch is complete (rows fetched = API count), any complaint we hold for
    that day that the API no longer returns is deleted. Two guards stop a bad
    response from wiping real data: nothing is deleted if the API says the day
    is empty, or if more than MAX_REMOVAL_SHARE of the day would go.

When the API is slow or down
    The daily bulk merge (load_bulk.py) runs first, so the warehouse is
    already up to date to the bulk file's date before this script starts.
    The API reload is a top-up, not the only source. So if the API stops
    answering (a day still fails after all retries) or gets so slow that the
    run would pass MAX_MINUTES, this script stops cleanly instead of crashing:
    days already loaded are kept, the day it was on is dropped (nothing from
    it is merged or deleted), the skipped days are written to raw.load_log,
    and the run carries on to reconcile, dbt and saving the warehouse.

How to run it (from the project folder, with the venv active)
    python src/ingestion/load_api.py                 newest day we hold minus 7 days, up to today
    python src/ingestion/load_api.py --days 1        only the newest day we hold (a quick test)
    python src/ingestion/load_api.py --start 2026-11-01 --end 2026-11-03
    python src/ingestion/load_api.py --max-minutes 10    give up on the API after 10 minutes
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
MAX_REMOVAL_SHARE = 0.05
MAX_MINUTES = 45


class ApiGaveUp(Exception):
    """The API failed after every retry, or the time budget ran out."""

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


def fetch_day(day, log, deadline=None):
    """Fetch every complaint received on one UTC day. Returns (records, api_count, as_of_utc).

    deadline is a time.monotonic() value. If it passes before the day is done,
    ApiGaveUp is raised and the half-fetched day is thrown away.
    """
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
        if deadline is not None and time.monotonic() > deadline:
            raise ApiGaveUp(f"time budget used up after {len(records):,} rows of {day}")
        try:
            data = get_with_retries(params, log)
        except requests.RequestException as error:
            raise ApiGaveUp(f"no answer for {day} after {MAX_TRIES} tries ({error})") from error
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


def remove_missing(con, day, api_count, log):
    """Delete complaints for `day` that the API no longer returns. Needs api_stage from this day."""
    held = con.execute("SELECT count(*) FROM raw.complaints WHERE date_received = ?", [day]).fetchone()[0]
    candidates = """
        FROM raw.complaints AS t
        WHERE t.date_received = $day
          AND NOT EXISTS (SELECT 1 FROM api_stage AS s WHERE s.complaint_id = t.complaint_id)
    """
    to_remove = con.execute(f"SELECT count(*) {candidates}", {"day": day}).fetchone()[0]
    if to_remove == 0:
        return 0
    if api_count == 0 or to_remove > MAX_REMOVAL_SHARE * held:
        log.warning("%s: %s complaints look removed, too many to trust, so nothing was deleted", day, to_remove)
        return 0
    con.execute(
        f"DELETE FROM raw.complaints WHERE complaint_id IN (SELECT t.complaint_id {candidates})",
        {"day": day},
    )
    return to_remove


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
    parser.add_argument("--max-minutes", type=float, default=MAX_MINUTES,
                        help=f"stop asking the API after this many minutes (default {MAX_MINUTES})")
    args = parser.parse_args()

    log = setup_logging()
    run_id = new_run_id()
    con = connect()
    days = pick_days(con, args)
    log.info("API run %s: loading %s UTC days, %s to %s", run_id, len(days), days[0], days[-1])

    deadline = time.monotonic() + args.max_minutes * 60
    totals = {"fetched": 0, "inserted": 0, "updated": 0, "changed": 0, "skipped_older": 0, "removed": 0}
    mismatched_days = []
    skipped_days = []
    for position, day in enumerate(days):
        started = utc_now()
        try:
            records, api_count, as_of_utc = fetch_day(day, log, deadline)
        except ApiGaveUp as reason:
            skipped_days = days[position:]
            log.warning(
                "Stopping the API load: %s. Skipped %s day(s), %s to %s. "
                "They still have the data from today's bulk merge.",
                reason, len(skipped_days), skipped_days[0], skipped_days[-1],
            )
            write_load_log(con, {
                "run_id": f"{run_id}-stopped",
                "source": "api",
                "started_at_utc": started,
                "finished_at_utc": utc_now(),
                "source_as_of_utc": None,
                "rows_in_source": 0,
                "rows_inserted": 0,
                "rows_updated": 0,
                "rows_changed": 0,
                "rows_skipped_older": 0,
                "table_rows_after": con.execute("SELECT count(*) FROM raw.complaints").fetchone()[0],
                "notes": f"API load stopped, skipped {skipped_days[0]} to {skipped_days[-1]}: {reason}"[:500],
            })
            break
        note = "ok"
        if len(records) != api_count:
            note = f"fetched {len(records)} but API count is {api_count}"
            mismatched_days.append(day)
            log.warning("%s: %s", day, note)

        counts = {"inserted": 0, "updated": 0, "changed": 0, "skipped_older": 0}
        removed = 0
        con.execute("BEGIN TRANSACTION")
        if records:
            stage_records(con, records)
            counts = merge_complaints(con, "api_stage", "api", as_of_utc, run_id)
            if len(records) == api_count:
                removed = remove_missing(con, day, api_count, log)
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
            "notes": f"day {day.isoformat()}: {note}; {removed} removed",
        })
        con.execute("COMMIT")

        totals["fetched"] += len(records)
        for key in counts:
            totals[key] += counts[key]
        totals["removed"] += removed
        log.info(
            "%s: %s fetched (API says %s) | %s new, %s refreshed, %s changed, %s skipped, %s removed",
            day, f"{len(records):,}", f"{api_count:,}", f"{counts['inserted']:,}",
            f"{counts['updated']:,}", f"{counts['changed']:,}", f"{counts['skipped_older']:,}", f"{removed:,}",
        )

    con.execute("CHECKPOINT")
    con.close()
    log.info(
        "Done: %s fetched, %s new, %s refreshed (%s changed), %s skipped, %s removed. "
        "Days with a count mismatch: %s. Days skipped because the API gave up: %s",
        f"{totals['fetched']:,}", f"{totals['inserted']:,}", f"{totals['updated']:,}",
        f"{totals['changed']:,}", f"{totals['skipped_older']:,}", f"{totals['removed']:,}",
        [d.isoformat() for d in mismatched_days] or "none",
        [d.isoformat() for d in skipped_days] or "none",
    )


if __name__ == "__main__":
    main()
