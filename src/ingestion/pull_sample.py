"""
Phase 1, Step 2: pull a sample of complaints spread across every month.

What this script does
    For every month from December 2011 (when the database starts) to the last
    full month, it sends one request that asks for:
      - the TOTAL number of complaints received that month (exact, from
        hits.total), and
      - up to 100 complaints from that month (the API's maximum page size).
    It saves two files:
      data/raw/monthly_counts.csv   one row per month: month, complaint count
      data/raw/sample_monthly.csv   the sampled complaints, all 15 fields

Why this design
    - Monthly counts cover ALL ~19 million complaints, without downloading
      them. The server counts for us. This is "pushing computation to the
      source".
    - 100 complaints per month gives us a few thousand rows from every era of
      the data, so we can see how fields, categories and data quality change
      over time.
    - Caveat (write this down!): the sample is NOT random. Within each month
      we get the 100 most recently received complaints, which come from the
      last day or two of the month. Good enough for spotting field formats
      and missing values, but not for measuring shares like "% Experian".

Bug we found and fixed (2026-11-06)
    The API docs say date_received_max is EXCLUSIVE (the end date is not
    included). Testing showed it is INCLUSIVE: Oct 1 to Oct 1 returned 27,811
    complaints, not 0. Our first run used "first day of next month" as the end,
    so every 1st of the month was counted twice (sum 19,467,745 vs API total
    18,965,764). Now each month ends on its LAST day, and the script checks
    that the months add up to the API total. That check is a "reconciliation".

Being polite to the server
    We wait half a second between requests, and retry a failed request up to
    3 times, waiting longer each time ("exponential backoff"). Phase 2's real
    ingestion script will use the same ideas.

How to run it (from the project folder, with the venv active)
    python src/ingestion/pull_sample.py
It makes about 180 requests and takes roughly 2 to 5 minutes.
"""

import time
from datetime import date, timedelta

import pandas as pd
import requests

BASE_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
FIRST_MONTH = date(2011, 12, 1)
PAGE_SIZE = 100
MAX_TRIES = 3


def month_starts(first, today):
    """Yield the first day of every month from `first` up to (not including) this month."""
    current = first
    this_month = date(today.year, today.month, 1)
    while current < this_month:
        yield current
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)


def next_month(d):
    return date(d.year + 1, 1, 1) if d.month == 12 else date(d.year, d.month + 1, 1)


def get_with_retries(params):
    """GET the API, retrying with exponential backoff (2s, 4s) on failure."""
    for attempt in range(1, MAX_TRIES + 1):
        try:
            response = requests.get(BASE_URL, params=params, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            if attempt == MAX_TRIES:
                raise
            wait = 2 ** attempt
            print(f"    attempt {attempt} failed ({error}); retrying in {wait}s")
            time.sleep(wait)


def main():
    counts = []
    samples = []

    for start in month_starts(FIRST_MONTH, date.today()):
        end = next_month(start) - timedelta(days=1)
        params = {
            "size": PAGE_SIZE,
            "sort": "created_date_desc",
            "no_aggs": "true",
            "date_received_min": start.isoformat(),
            "date_received_max": end.isoformat(),
        }
        data = get_with_retries(params)

        total = data["hits"]["total"]
        records = [hit["_source"] for hit in data["hits"]["hits"]]

        counts.append({
            "month": start.isoformat()[:7],
            "complaints": total["value"],
            "count_is_exact": total["relation"] == "eq",
        })
        for record in records:
            record["sample_month"] = start.isoformat()[:7]
            samples.append(record)

        print(f"{start.isoformat()[:7]}: {total['value']:>8,} complaints, sampled {len(records)}")
        time.sleep(0.5)

    current_month = date(date.today().year, date.today().month, 1)
    partial = get_with_retries({"size": 1, "no_aggs": "true",
                                "date_received_min": current_month.isoformat()})
    partial_count = partial["hits"]["total"]["value"]
    overall = get_with_retries({"size": 1, "no_aggs": "true"})
    api_total = overall["hits"]["total"]["value"]

    counts_df = pd.DataFrame(counts)
    sample_df = pd.DataFrame(samples)

    counts_df.to_csv("data/raw/monthly_counts.csv", index=False)
    sample_df.to_csv("data/raw/sample_monthly.csv", index=False)

    print()
    print(f"Months covered: {len(counts_df)}")
    print(f"Sum of monthly counts: {counts_df['complaints'].sum():,}")
    print(f"All counts exact: {counts_df['count_is_exact'].all()}")
    print(f"Current partial month ({current_month.isoformat()[:7]}): {partial_count:,}")
    print(f"Months + partial month: {counts_df['complaints'].sum() + partial_count:,}")
    print(f"API total for everything: {api_total:,}")
    difference = api_total - (counts_df['complaints'].sum() + partial_count)
    print(f"Reconciliation difference: {difference:,} (0 means every complaint counted exactly once)")
    print(f"Sampled complaints: {len(sample_df):,}")
    print("Saved data/raw/monthly_counts.csv and data/raw/sample_monthly.csv")


if __name__ == "__main__":
    main()
