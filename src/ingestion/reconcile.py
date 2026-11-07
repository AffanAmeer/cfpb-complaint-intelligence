"""
Reconciliation: prove the warehouse matches the source after a load.

A load that "ran without errors" can still be wrong: rows skipped, counted
twice, or put on the wrong day. These checks compare the warehouse with
the API's own counts, and check the table's basic integrity. Every result is
printed and saved to raw.reconciliation_log, so we have a history.

The checks
    1. unique_complaint_id   no complaint ID appears twice
    2. dates_in_range        every date_received is between Dec 2011 and today
    3. total_vs_api          rows up to our newest day = API count for the same range
    4. monthly_vs_api        the same, month by month (about 180 requests)
    5. daily_vs_api          the same, day by day for the last 14 days we hold

Checks 3 to 5 also test our time zone assumption. The API counts use UTC
days, so if the bulk file's dates were US Eastern days instead, the daily
counts would not match.

Why the API counts might not match (even if the loader is right)
    - CFPB removed a complaint after we loaded it (we keep the old row).
    - CFPB added complaints for a past day after our last load.
    Either way, a difference is worth looking at, so the check reports FAIL
    and the script exits with code 1. That will let GitHub Actions flag it in Phase 4.

How to run it (from the project folder, with the venv active)
    python src/ingestion/reconcile.py
    python src/ingestion/reconcile.py --skip-monthly    faster, skips check 4
"""

import argparse
import sys
import time
from datetime import date, timedelta

from load_api import get_with_retries
from warehouse import connect, setup_logging, utc_now

FIRST_DAY = date(2011, 12, 1)
DAILY_CHECK_DAYS = 14


def api_count(log, start, end):
    """Number of complaints the API holds with date_received from start to end (both included)."""
    data = get_with_retries({
        "size": 1,
        "no_aggs": "true",
        "date_received_min": start.isoformat(),
        "date_received_max": end.isoformat(),
    }, log)
    time.sleep(0.2)
    return data["hits"]["total"]["value"]


def month_ranges(first, last):
    """(first day, last day) of every month from `first` to `last`, the last one cut at `last`."""
    current = first
    while current <= last:
        nxt = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
        yield current, min(nxt - timedelta(days=1), last)
        current = nxt


def main():
    parser = argparse.ArgumentParser(description="Reconcile raw.complaints against the CFPB API.")
    parser.add_argument("--skip-monthly", action="store_true", help="skip the month-by-month check")
    args = parser.parse_args()

    log = setup_logging()
    con = connect()
    results = []

    def record(name, status, warehouse_value, source_value, details=""):
        difference = None if source_value is None else warehouse_value - source_value
        results.append((utc_now(), name, status, warehouse_value, source_value, difference, details))
        log.info("%-20s %-4s warehouse=%s source=%s %s", name, status, warehouse_value, source_value, details)

    rows, distinct_ids, oldest, newest = con.execute(
        "SELECT count(*), count(DISTINCT complaint_id), min(date_received), max(date_received) FROM raw.complaints"
    ).fetchone()
    if rows == 0:
        raise SystemExit("raw.complaints is empty, nothing to reconcile.")
    log.info("Warehouse holds %s complaints, %s to %s", f"{rows:,}", oldest, newest)

    record("unique_complaint_id", "PASS" if rows == distinct_ids else "FAIL", distinct_ids, rows,
           "distinct IDs vs rows")

    in_range = FIRST_DAY <= oldest and newest <= utc_now().date()
    record("dates_in_range", "PASS" if in_range else "FAIL", rows, None, f"{oldest} to {newest}")

    api_total = api_count(log, FIRST_DAY, newest)
    record("total_vs_api", "PASS" if rows == api_total else "FAIL", rows, api_total, f"up to {newest}")

    wh_by_day = dict(con.execute(
        "SELECT date_received, count(*) FROM raw.complaints GROUP BY 1"
    ).fetchall())

    if not args.skip_monthly:
        bad_months = []
        wh_months, api_months = 0, 0
        for start, end in month_ranges(FIRST_DAY, newest):
            wh = sum(n for d, n in wh_by_day.items() if start <= d <= end)
            api = api_count(log, start, end)
            wh_months += wh
            api_months += api
            if wh != api:
                bad_months.append(f"{start:%Y-%m}: {wh - api:+,}")
        details = "all months match" if not bad_months else "; ".join(bad_months[:12])
        record("monthly_vs_api", "PASS" if not bad_months else "FAIL", wh_months, api_months, details)

    bad_days = []
    wh_days, api_days = 0, 0
    for i in range(DAILY_CHECK_DAYS):
        day = newest - timedelta(days=i)
        wh = wh_by_day.get(day, 0)
        api = api_count(log, day, day)
        wh_days += wh
        api_days += api
        if wh != api:
            bad_days.append(f"{day}: {wh - api:+,}")
    details = f"last {DAILY_CHECK_DAYS} days all match" if not bad_days else "; ".join(bad_days)
    record("daily_vs_api", "PASS" if not bad_days else "FAIL", wh_days, api_days, details)

    con.executemany("INSERT INTO raw.reconciliation_log VALUES (?, ?, ?, ?, ?, ?, ?)", results)
    con.close()

    failed = [r[1] for r in results if r[2] == "FAIL"]
    if failed:
        log.warning("Reconciliation FAILED: %s", ", ".join(failed))
        sys.exit(1)
    log.info("Reconciliation passed: all %s checks", len(results))


if __name__ == "__main__":
    main()
