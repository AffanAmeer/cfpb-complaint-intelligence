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
    CFPB keeps publishing complaints for past days for weeks, and sometimes
    removes complaints. The loaders handle both (load_bulk.py merges a fresh
    full copy every day, load_api.py reloads the last 7 days), but the bulk
    file is made once a day, so by the time this script asks the API, a few
    late complaints have usually appeared that no file had yet.

    So each check has three results:
    PASS  exact match.
    WARN  a small gap, only where late publishing is expected: days outside
          the API's 7-day reload, in the last LATE_WINDOW_DAYS days, within
          the tolerances below. The run carries on.
    FAIL  anything else. The script exits with code 1, and GitHub Actions
          marks the run as failed.
    Days the API load just reloaded, and months older than LATE_WINDOW_DAYS,
    must always match exactly.

How to run it (from the project folder, with the venv active)
    python src/ingestion/reconcile.py
    python src/ingestion/reconcile.py --skip-monthly    faster, skips check 4
"""

import argparse
import sys
import time
from datetime import date, timedelta

from load_api import LOOKBACK_DAYS, get_with_retries
from warehouse import connect, setup_logging, utc_now

FIRST_DAY = date(2011, 12, 1)
DAILY_CHECK_DAYS = 14
LATE_WINDOW_DAYS = 120
TOTAL_TOLERANCE = 0.0005
MONTH_TOLERANCE = 0.01
DAY_TOLERANCE = 0.02


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


def worst(statuses):
    """The overall result of a check made of many parts: any FAIL wins, then any WARN."""
    return "FAIL" if "FAIL" in statuses else "WARN" if "WARN" in statuses else "PASS"


def judge(gap, source_value, tolerance, late_allowed):
    """PASS for an exact match, WARN for a small gap where late publishing is expected, else FAIL."""
    if gap == 0:
        return "PASS"
    if late_allowed and abs(gap) <= tolerance * source_value:
        return "WARN"
    return "FAIL"


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
    record("total_vs_api", judge(rows - api_total, api_total, TOTAL_TOLERANCE, True),
           rows, api_total, f"up to {newest}")

    reloaded_from = newest - timedelta(days=LOOKBACK_DAYS)
    late_from = newest - timedelta(days=LATE_WINDOW_DAYS)

    wh_by_day = dict(con.execute(
        "SELECT date_received, count(*) FROM raw.complaints GROUP BY 1"
    ).fetchall())

    if not args.skip_monthly:
        bad_months = []
        statuses = set()
        wh_months, api_months = 0, 0
        for start, end in month_ranges(FIRST_DAY, newest):
            wh = sum(n for d, n in wh_by_day.items() if start <= d <= end)
            api = api_count(log, start, end)
            wh_months += wh
            api_months += api
            status = judge(wh - api, api, MONTH_TOLERANCE, end >= late_from)
            statuses.add(status)
            if status != "PASS":
                bad_months.append(f"{start:%Y-%m}: {wh - api:+,}{'' if status == 'WARN' else ' (FAIL)'}")
        details = "all months match" if not bad_months else "; ".join(bad_months[:12])
        record("monthly_vs_api", worst(statuses), wh_months, api_months, details)

    bad_days = []
    statuses = set()
    wh_days, api_days = 0, 0
    for i in range(DAILY_CHECK_DAYS):
        day = newest - timedelta(days=i)
        wh = wh_by_day.get(day, 0)
        api = api_count(log, day, day)
        wh_days += wh
        api_days += api
        status = judge(wh - api, api, DAY_TOLERANCE, day < reloaded_from)
        statuses.add(status)
        if status != "PASS":
            bad_days.append(f"{day}: {wh - api:+,}{'' if status == 'WARN' else ' (FAIL)'}")
    details = f"last {DAILY_CHECK_DAYS} days all match" if not bad_days else "; ".join(bad_days)
    record("daily_vs_api", worst(statuses), wh_days, api_days, details)

    con.executemany("INSERT INTO raw.reconciliation_log VALUES (?, ?, ?, ?, ?, ?, ?)", results)
    con.close()

    failed = [r[1] for r in results if r[2] == "FAIL"]
    if failed:
        log.warning("Reconciliation FAILED: %s", ", ".join(failed))
        sys.exit(1)
    warned = [r[1] for r in results if r[2] == "WARN"]
    if warned:
        log.info("Reconciliation passed with small late-publishing gaps in: %s", ", ".join(warned))
    else:
        log.info("Reconciliation passed: all %s checks", len(results))


if __name__ == "__main__":
    main()
