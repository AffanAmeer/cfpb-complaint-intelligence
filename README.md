# Banking Complaint Intelligence System

A data analytics project that uses the CFPB's public Consumer Complaint Database to explore trends in banking complaints, identify unusual spikes, and uncover common customer issues.

The goal is to build an end-to-end pipeline that takes raw complaint data and turns it into useful insights through data engineering, SQL analysis, statistical methods, and NLP.

**Status:** In progress. The full complaint history (18,965,764 complaints, Dec 2011 to Nov 2026) is loaded into DuckDB, reconciles exactly with the CFPB API, and is modelled into a tested star schema with dbt.

## Architecture

CFPB API → Python data ingestion → DuckDB → dbt data models and tests → SQL analysis and statistical detection → NLP classification → Power BI dashboard and automated reports

## Tech Stack

- **Python:** Data collection, cleaning, and analysis using requests and pandas
- **Database:** DuckDB for storing and querying complaint data
- **Data modelling:** dbt Core and dbt-duckdb for building and testing the warehouse
- **Automation:** GitHub Actions for scheduled data updates
- **Machine learning:** scikit-learn for text classification and complaint analysis
- **Reporting:** Power BI, DAX, Power Query, and Excel

## How to Run

1. Clone the repository and navigate into the project folder.
2. Create and activate a virtual environment:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```

3. Install the dependencies:

   ```bash
   python -m pip install -r requirements.txt
   ```

4. Load the data (all commands from the project folder):

   ```bash
   curl -L -o data/raw/complaints.csv.zip https://files.consumerfinance.gov/ccdb/complaints.csv.zip
   python src/ingestion/load_bulk.py
   python src/ingestion/load_api.py
   python src/ingestion/reconcile.py
   ```

5. Build and test the star schema:

   ```bash
   cd dbt
   dbt build
   dbt source freshness
   ```

## Ingestion

The full history comes from CFPB's bulk CSV, and the API keeps it up to date. Loading 19 million complaints through the API would take about 190,000 requests at 100 rows each.

- `load_bulk.py` is the backfill. It unzips the 5.7 GB CSV, checks it (row count, duplicate IDs, unparseable dates), and loads it into `raw.complaints` in under a minute.
- `load_api.py` is the incremental load. It re-pulls the last 7 days (UTC) from the API, paging with `search_after`, because complaints change after they are filed (for example "In progress" becomes "Closed with explanation"). Each day's fetched rows must equal the API's count for that day.
- Both loaders upsert on `complaint_id` with `MERGE`, so re-running a load never creates duplicates. A row is only overwritten by data that is at least as recent, so an old bulk file can't undo newer API data.
- Every run is recorded in `raw.load_log` (rows inserted, updated, changed, skipped).
- `reconcile.py` compares the warehouse with the API: duplicate IDs, the total, every month, and the last 14 days. It exits with an error if anything differs. First run (2026-11-07): all 5 checks passed, and all 180 months match.
- Dates are UTC. The API's date filter uses UTC days, and the daily check confirmed the bulk file does too.

## Data Model

dbt (`dbt/`) turns `raw.complaints` into a star schema in the same DuckDB file, in three layers:

- **Staging** (`staging.stg_complaints`, a view): one row per complaint, with trimmed text, labelled blanks, standard state codes and the join keys.
- **Marts** (tables): `fact_complaints` (one row per complaint, 18,965,764 rows) with `dim_product` (127), `dim_issue` (442), `dim_company` (8,198), `dim_state` (63) and `dim_date` (one row per day, 2011 to 2026).
- **Reference** (seeds): small hand-checked CSVs that dbt loads as tables.

Decisions worth knowing:

- **Products were renamed twice.** CFPB used 21 product names across three naming schemes (2011-2017, 2017-2023, 2023 onward), and split some products (for example "Credit card or prepaid card" became two). `seeds/product_group_map.csv` maps every old name, using the sub-product where a product was split, onto CFPB's current 11 products. This gives `product_group`, which can be compared across years.
- **Company names** are merged when they differ only by capitals, spaces or punctuation (8,210 spellings become 8,198 companies, for example "ONEMAIN FINANCE CORPORATION" and "OneMain Finance Corporation"). Different legal entities of one group are not merged.
- **Credit bureaus** are flagged (`dim_company.is_credit_bureau`). Equifax, TransUnion and Experian account for 78.9% of all complaints, so most analysis should show them separately.
- **Keys** are md5 hashes of the natural values, so they are stable between runs and portable to Databricks. Date keys are integers like `20261107`.

Tests (57, all passing): unique and not-null keys, every fact key exists in its dimension, accepted values for categories, the fact table has exactly one row per raw complaint, every raw product is mapped, plus two unit tests for the product mapping and company merging logic. `dbt source freshness` warns if no load has happened in 2 days. A full build of 19M rows takes about 7 seconds on a MacBook Air.

## Key Findings

Added once results exist. Every number here will be reproducible from this repo.

## Data Source and Limitations

- Public U.S. data from the CFPB Consumer Complaint Database.
- Complaints are not a representative sample of all consumers, and narratives are published only when consumers opt in.
- The methods transfer directly to Canadian banks' complaint data.

## Roadmap

- [x] 0. Setup
- [x] 1. Explore the data and API
- [x] 2. Ingestion + incremental loads
- [x] 3. dbt star schema + tests
- [ ] 4. GitHub Actions scheduling
- [ ] 5. SQL analysis + KPIs
- [ ] 6. Statistics: spike detection
- [ ] 7. Text classifier
- [ ] 8. Power BI dashboard
- [ ] 9. Monthly brief, deck, Excel export
- [ ] 10. Port to Databricks
- [ ] 11. Architecture diagram + write-up
