# Banking Complaint Intelligence System

A data analytics project that uses the CFPB's public Consumer Complaint Database to explore trends in banking complaints, identify unusual spikes, and uncover common customer issues.

The goal is to build an end-to-end pipeline that takes raw complaint data and turns it into useful insights through data engineering, SQL analysis, statistical methods, and NLP.

**Status:** In progress. The full complaint history (18,965,764 complaints, Dec 2011 to Nov 2026) is loaded into DuckDB and reconciles exactly with the CFPB API.

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

## Ingestion

The full history comes from CFPB's bulk CSV, and the API keeps it up to date. Loading 19 million complaints through the API would take about 190,000 requests at 100 rows each.

- `load_bulk.py` is the backfill. It unzips the 5.7 GB CSV, checks it (row count, duplicate IDs, unparseable dates), and loads it into `raw.complaints` in under a minute.
- `load_api.py` is the incremental load. It re-pulls the last 7 days (UTC) from the API, paging with `search_after`, because complaints change after they are filed (for example "In progress" becomes "Closed with explanation"). Each day's fetched rows must equal the API's count for that day.
- Both loaders upsert on `complaint_id` with `MERGE`, so re-running a load never creates duplicates. A row is only overwritten by data that is at least as recent, so an old bulk file can't undo newer API data.
- Every run is recorded in `raw.load_log` (rows inserted, updated, changed, skipped).
- `reconcile.py` compares the warehouse with the API: duplicate IDs, the total, every month, and the last 14 days. It exits with an error if anything differs. First run (2026-11-07): all 5 checks passed, and all 180 months match.
- Dates are UTC. The API's date filter uses UTC days, and the daily check confirmed the bulk file does too.

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
- [ ] 3. dbt star schema + tests
- [ ] 4. GitHub Actions scheduling
- [ ] 5. SQL analysis + KPIs
- [ ] 6. Statistics: spike detection
- [ ] 7. Text classifier
- [ ] 8. Power BI dashboard
- [ ] 9. Monthly brief, deck, Excel export
- [ ] 10. Port to Databricks
- [ ] 11. Architecture diagram + write-up
