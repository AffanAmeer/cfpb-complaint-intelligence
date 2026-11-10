# Banking Complaint Intelligence System

[![Daily pipeline](https://github.com/AffanAmeer/cfpb-complaint-intelligence/actions/workflows/daily_pipeline.yml/badge.svg)](https://github.com/AffanAmeer/cfpb-complaint-intelligence/actions/workflows/daily_pipeline.yml)

A data analytics project that uses the CFPB's public Consumer Complaint Database to explore trends in banking complaints, identify unusual spikes, and uncover common customer issues.

The goal is to build an end-to-end pipeline that takes raw complaint data and turns it into useful insights through data engineering, SQL analysis, statistical methods, and NLP.

**Status:** In progress. The full complaint history (19,028,339 complaints, Dec 2011 to Nov 2026, as of 2026-11-09) is loaded into DuckDB, reconciles exactly with the CFPB API, and is modelled into a tested star schema with dbt. GitHub Actions refreshes it every day, and a set of SQL queries turns it into KPIs.

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

6. Run the KPI queries (from the project folder). Each result is saved as a CSV in `reports/kpis/`:

   ```bash
   cd ..
   python src/analysis/run_kpis.py
   ```

   To skip steps 4 and 5, download the latest warehouse from the [`warehouse` release](https://github.com/AffanAmeer/cfpb-complaint-intelligence/releases/tag/warehouse), unzip it with `gunzip`, and put it at `data/warehouse/complaints.duckdb`.

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

## Automation

`.github/workflows/daily_pipeline.yml` runs the whole pipeline on GitHub Actions every day at 18:37 UTC, after CFPB's daily update. It can also be started by hand from the Actions tab.

1. Check that the CFPB API and bulk file are reachable (`check_source.py`), so a block fails in seconds, not after a long run.
2. Download the saved warehouse (if none exists, the next step rebuilds it).
3. Merge the latest bulk file (`load_bulk.py`). This catches complaints CFPB publishes late for past days, and removes complaints CFPB has taken out.
4. Load the last 7 days from the API (`load_api.py`), which is fresher than the bulk file.
5. Reconcile with the API (`reconcile.py`).
6. Build and test the star schema (`dbt build`, `dbt source freshness`).
7. Save the warehouse.
8. Write a run summary (`run_summary.py`) and keep the logs for 30 days.

Decisions worth knowing:

- **Where the data lives between runs.** Every run gets a fresh machine, so the DuckDB file (830 MB) would be lost. The pipeline gzips it and stores it as a file on the [`warehouse` release](https://github.com/AffanAmeer/cfpb-complaint-intelligence/releases/tag/warehouse), replacing it each day. Anyone can download the latest warehouse from there and open it with DuckDB.
- **Self-healing.** If the saved file is missing, the run rebuilds the full history from the bulk file in under a minute, then carries on as normal.
- **A failed reconciliation still saves the data.** A mismatch usually means CFPB changed past days, not that the load was wrong. So the run saves the warehouse first and then marks itself as failed, which sends an email. If `dbt build` fails, nothing is saved, and the next run's 7-day lookback re-pulls the same days.
- **Late complaints.** The first scheduled runs (Nov 7 and 8) failed reconciliation: the warehouse was about 8,400 complaints short, almost all in late October. CFPB keeps publishing complaints for past days for weeks, and a 7-day API lookback never goes back for them. It also removes some complaints (a few hundred in September). The fix merges the full bulk file every run (under a minute) and deletes complaints that are no longer in it. Because the bulk file is made once a day, a few late complaints can still appear before reconciliation runs, so those checks allow a small, stated gap (WARN) only on days outside the API reload and in the last 120 days. Everything else must match exactly.
- **Changed complaints are caught.** The Nov 7 and 8 runs updated 4,335 and 3,929 complaints whose values had changed, mostly "In progress" becoming closed.
- **One run at a time.** A concurrency group makes a second run wait, so two runs can never overwrite each other's file.
- **No secrets to manage.** The run uses the temporary token GitHub creates for each run, with permission only to write releases.

First run (2026-11-07, rebuilding from the bulk file): 23m 48s in total. The API load took 16m 20s, reconciliation 4m 22s, the bulk rebuild 55s and `dbt build` 52s. All 5 reconciliation checks passed, and all 18,965,764 complaints reached `fact_complaints`.

## Analysis

The KPIs are plain SQL files in `sql/analysis/`, run by `src/analysis/run_kpis.py` against the warehouse (read-only). All 7 queries take about 2 seconds on 19 million rows. Every KPI is defined in [docs/kpi_definitions.md](docs/kpi_definitions.md), and the results are written up in [docs/analysis_findings.md](docs/analysis_findings.md).

| Query | What it answers |
| --- | --- |
| `_window.sql` | Sets the reporting window: the last 12 complete months and the 12 before them. |
| `00_data_maturity.sql` | Why the newest weeks are left out (they are still being published). |
| `01_headline_kpis.sql` | The scorecard: complaints, bureau share, timely and relief rates, this year vs last. |
| `02_monthly_trend.sql` | Every month since 2011, with month-over-month, year-over-year and a 3-month rolling average. |
| `03_product_yoy.sql` | Complaints by product group, year over year. |
| `04_top_companies.sql` | The top companies, ranked separately for the credit bureaus and everyone else. |
| `05_top_issues_by_product.sql` | The top 3 issues inside each product. |
| `06_company_response_scorecard.sql` | Timely and relief rates for companies with at least 1,000 complaints. |

Decisions worth knowing:

- **Only complete months.** CFPB publishes most complaints after the company answers, so the newest weeks are always short. In the data as of 2026-11-09, non-bureau complaints in the week of 2026-10-26 were at 46% of a normal week. A month counts only once it ended 30 days before the newest complaint, and the window moves forward by itself.
- **Credit bureaus are reported separately.** Equifax, TransUnion and Experian are about 88% of recent complaints and would hide any change at banks.
- **Rates use closed complaints only.** "In progress" complaints are always marked timely and can't have relief yet.
- **Changes in rates are in percentage points**, changes in counts are in percent.
- **Counts are not quality scores.** CFPB doesn't publish customer numbers, so a big company ranks high by being big.
- **No company response time.** The data says whether an answer was on time, not when it came, so there is no "days to respond" KPI.

## Key Findings

Data as of 2026-11-09. Current 12 months = Oct 2025 to Sep 2026, compared with the 12 months before. Every number comes from the CSVs in `reports/kpis/` (a snapshot; a later run will differ slightly). Details in [docs/analysis_findings.md](docs/analysis_findings.md).

- Complaints rose 46.0% (4,800,962 to 7,010,093), but most of that is the three credit bureaus (+49.9%). Complaints about all other companies rose 23.1% (699,858 to 861,811).
- That growth is slowing: non-bureau complaints were up 68.8% year over year in Dec 2025 and 11.5% in Sep 2026.
- Debt collection is now the biggest non-bureau product (292,812 complaints, 34.0% of the segment, +61.6%). Its top issue is "Attempts to collect debt not owed" (43.3%).
- 99.55% of closed complaints were answered on time, so the timely rate barely separates companies. It works as an exception report: MOHELA answered 27.76% of 8,551 closed complaints on time.
- Monetary relief at non-bureau companies rose from 3.58% to 3.92% of closed complaints. Relief rates differ a lot between big banks (Bank of America 24.81%, Capital One 5.68%), but their product mixes differ too, so that is not a fair comparison on its own.

## Data Source and Limitations

- Public U.S. data from the CFPB Consumer Complaint Database.
- Complaints are not a representative sample of all consumers, and narratives are published only when consumers opt in.
- The methods transfer directly to Canadian banks' complaint data.

## Roadmap

- [x] 0. Setup
- [x] 1. Explore the data and API
- [x] 2. Ingestion + incremental loads
- [x] 3. dbt star schema + tests
- [x] 4. GitHub Actions scheduling
- [x] 5. SQL analysis + KPIs
- [ ] 6. Statistics: spike detection
- [ ] 7. Text classifier
- [ ] 8. Power BI dashboard
- [ ] 9. Monthly brief, deck, Excel export
- [ ] 10. Port to Databricks
- [ ] 11. Architecture diagram + write-up
