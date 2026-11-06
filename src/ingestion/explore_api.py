"""
Phase 1, Step 1: a first look at the CFPB Consumer Complaint API.

What this script does
    1. Sends ONE request to the CFPB API asking for the 3 newest complaints.
    2. Prints what came back: status code, the shape of the response,
       how many complaints exist in total, and every field in one complaint.
    3. Saves the raw response to data/raw/api_sample.json so we can study it
       without calling the API again.

Why we start this small
    Before writing an ingestion pipeline (Phase 2) we need to know what the
    data actually looks like. Asking for 3 rows is fast, polite to the server,
    and enough to learn the field names and data types. This is called
    "profiling the source" or "exploratory data access".

Note on the API (checked 2026-11-06 against the official spec,
github.com/cfpb/ccdb5-api swagger-config.yaml)
    - "format=json" was retired in July 2026. Leaving "format" out gets JSON
      back; "format=csv" is the only format value left.
    - "size" can be at most 100 per request.
    - Complaint narratives were removed from the database in September 2026.
    - The site's security layer (Akamai) returned 403 when we sent a custom
      User-Agent header, but allowed requests' default one. So we send none.

How to run it (from the project folder, with the venv active)
    python src/ingestion/explore_api.py
"""

import json
import sys

import requests

BASE_URL = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"

PARAMS = {
    "size": 3,
    "sort": "created_date_desc",
    "no_aggs": "true",
}


def main():
    response = requests.get(BASE_URL, params=PARAMS, timeout=60)

    print("Status code:", response.status_code)
    print("URL we called:", response.url)
    if not response.ok:
        print("Server said no. First 500 characters of its reply:")
        print(response.text[:500])
    response.raise_for_status()

    data = response.json()
    print("Top-level keys:", list(data.keys()))

    if "hits" not in data:
        print("Unexpected response shape. First 1000 characters:")
        print(json.dumps(data)[:1000])
        sys.exit(1)

    hits = data["hits"]
    print("Total complaints matching:", hits.get("total"))

    records = [hit["_source"] for hit in hits["hits"]]
    print("Records returned in this response:", len(records))

    first = records[0]
    print(f"\nFields in one complaint ({len(first)} fields):")
    for key in sorted(first):
        value = first[key]
        preview = str(value).replace("\n", " ")[:50]
        print(f"  {key:32} {type(value).__name__:6} {preview}")

    with open("data/raw/api_sample.json", "w") as f:
        json.dump(data, f, indent=2)
    print("\nSaved the full response to data/raw/api_sample.json")


if __name__ == "__main__":
    main()
