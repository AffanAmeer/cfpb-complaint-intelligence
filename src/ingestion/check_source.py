"""
Source check: can this machine reach CFPB at all?

Why this exists
    The pipeline runs on GitHub's machines, not on my laptop. CFPB's website
    sits behind Akamai, a firewall that blocks traffic it thinks is a bot, and
    cloud data centres are often blocked. If CFPB refuses us, every later step
    would fail with a confusing error after minutes of work. This script fails
    in a few seconds instead, with a clear message. That is called failing fast.

What it checks
    1. The search API answers, and how many complaints it holds.
    2. The bulk CSV zip is downloadable (a HEAD request: headers only, no download).

Only the bulk file is required. The bulk merge brings the warehouse up to
date on its own, and the API is just a top-up (load_api.py stops cleanly if
the API is down). So if only the API fails, this prints a warning and the
run carries on. The API being down then shows up later, in reconcile.

How to run it (from the project folder, with the venv active)
    python src/ingestion/check_source.py
It exits with code 1 if the bulk file can't be reached, which turns a GitHub
Actions step red.
"""

import sys

import requests

from load_api import BASE_URL

BULK_URL = "https://files.consumerfinance.gov/ccdb/complaints.csv.zip"


def check_api():
    response = requests.get(BASE_URL, params={"size": 1, "no_aggs": "true"}, timeout=30)
    print(f"API: HTTP {response.status_code}")
    if response.status_code != 200:
        print(f"API refused us. First 300 characters of the reply:\n{response.text[:300]}")
        return False
    data = response.json()
    total = data["hits"]["total"]["value"]
    last_indexed = data["_meta"]["last_indexed"]
    print(f"API: {total:,} complaints, last indexed {last_indexed}")
    return True


def check_bulk():
    response = requests.head(BULK_URL, allow_redirects=True, timeout=30)
    print(f"Bulk zip: HTTP {response.status_code}")
    if response.status_code != 200:
        return False
    size_mb = int(response.headers.get("Content-Length", 0)) / 1e6
    print(f"Bulk zip: {size_mb:,.0f} MB, last modified {response.headers.get('Last-Modified')}")
    return True


def main():
    results = {}
    for name, check in [("api", check_api), ("bulk", check_bulk)]:
        try:
            results[name] = check()
        except requests.RequestException as error:
            print(f"{name}: request failed: {error}")
            results[name] = False
    if not results["bulk"]:
        print("FAILED: the CFPB bulk file is not reachable from this machine.")
        sys.exit(1)
    if not results["api"]:
        print("::warning::CFPB API not reachable. Carrying on with the bulk file; "
              "the API top-up and reconcile will likely be skipped or fail.")
        return
    print("OK: CFPB API and bulk file are both reachable.")


if __name__ == "__main__":
    main()
