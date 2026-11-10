"""
Load complaint narratives from the CFPB Narratives Archive into a small DuckDB file.

Why a separate source
    In August 2026 the CFPB stopped publishing complaint narratives. The bulk file
    our warehouse loads no longer has the "Consumer complaint narrative" column. The
    narratives that were already public were moved to the CFPB's FOIA Reading Room:
    https://www.consumerfinance.gov/foia-requests/foia-electronic-reading-room/cfpb-consumer-complaint-database-narratives-archive/
    The archive is split into zip files by month (CCDB_Export_<n>_<months>.zip).

What this script does
    1. Reads every CCDB_Export_*.zip in data/raw/narratives/ (download them first).
    2. Keeps only complaints that have a narrative.
    3. Maps CFPB's product name onto the same product groups the warehouse uses
       (dbt/seeds/product_group_map.csv), so the classifier's labels match the
       rest of the project.
    4. Drops duplicate complaint IDs (the archive files should not overlap, but we
       check instead of assuming).
    5. Saves one table, narratives, to data/narratives/narratives.duckdb.

How to run it on the Mac (project folder, venv active)
    python src/classifier/load_narratives.py
"""

import zipfile
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_DIR = PROJECT_ROOT / "data" / "raw" / "narratives"
SEED_PATH = PROJECT_ROOT / "dbt" / "seeds" / "product_group_map.csv"
DB_PATH = PROJECT_ROOT / "data" / "narratives" / "narratives.duckdb"

COLUMNS = {
    "Complaint ID": "complaint_id",
    "Date received": "date_received",
    "Product": "product",
    "Sub-product": "sub_product",
    "Issue": "issue",
    "Company": "company",
    "Consumer complaint narrative": "narrative",
}


def read_archive_file(path):
    """Read one archive zip and return only the rows that have a narrative."""
    with zipfile.ZipFile(path) as z:
        csv_names = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if len(csv_names) != 1:
            raise ValueError(f"{path.name}: expected one CSV inside, found {csv_names}")
        parts = []
        with z.open(csv_names[0]) as f:
            # Read in chunks: each file is about 1 million rows, but only a few
            # percent have a narrative, so we filter as we go to save memory.
            for chunk in pd.read_csv(f, usecols=list(COLUMNS), dtype=str, chunksize=200_000):
                chunk = chunk.rename(columns=COLUMNS)
                parts.append(chunk[chunk["narrative"].notna()])
    df = pd.concat(parts, ignore_index=True)
    df["source_file"] = path.name
    return df


def add_product_group(df, seed):
    """
    Same two-step match as dbt/models/marts/dim_product.sql:
      1. exact match on product + sub_product, then
      2. the product's default row (empty sub_product).
    """
    exact = seed[seed["sub_product"].notna()][["product", "sub_product", "product_group_short"]]
    default = seed[seed["sub_product"].isna()][["product", "product_group_short"]]

    out = df.merge(exact, on=["product", "sub_product"], how="left")
    out = out.merge(default, on="product", how="left", suffixes=("", "_default"))
    out["product_group"] = out["product_group_short"].fillna(out["product_group_short_default"])
    return out.drop(columns=["product_group_short", "product_group_short_default"])


def main():
    files = sorted(ARCHIVE_DIR.glob("CCDB_Export_*.zip"))
    if not files:
        raise SystemExit(f"No CCDB_Export_*.zip files in {ARCHIVE_DIR}. Download them first.")

    frames = []
    for path in files:
        df = read_archive_file(path)
        print(f"{path.name}: {len(df):,} complaints with a narrative")
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    before = len(df)
    df = df.drop_duplicates(subset="complaint_id", keep="last")
    print(f"Duplicate complaint IDs dropped: {before - len(df):,}")

    seed = pd.read_csv(SEED_PATH, dtype=str)
    df = add_product_group(df, seed)
    unmapped = df[df["product_group"].isna()]["product"].value_counts()
    if len(unmapped):
        raise SystemExit(f"Products missing from the seed, add them first:\n{unmapped}")

    df["complaint_id"] = df["complaint_id"].astype("int64")
    df["date_received"] = pd.to_datetime(df["date_received"]).dt.date

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB_PATH)) as con:
        con.register("df", df)
        con.execute("create or replace table narratives as select * from df order by date_received, complaint_id")
        n, first, last = con.execute(
            "select count(*), min(date_received), max(date_received) from narratives"
        ).fetchone()
    print(f"Saved {n:,} narratives ({first} to {last}) to {DB_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
