# Banking Complaint Intelligence System

A data analytics project that uses the CFPB's public Consumer Complaint Database to explore trends in banking complaints, identify unusual spikes, and uncover common customer issues.

The goal is to build an end-to-end pipeline that takes raw complaint data and turns it into useful insights through data engineering, SQL analysis, statistical methods, and NLP.

**Status:** In progress. Initial project setup is complete.

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

## Key Findings

Added once results exist. Every number here will be reproducible from this repo.

## Data Source and Limitations

- Public U.S. data from the CFPB Consumer Complaint Database.
- Complaints are not a representative sample of all consumers, and narratives are published only when consumers opt in.
- The methods transfer directly to Canadian banks' complaint data.

## Roadmap

- [x] 0. Setup
- [ ] 1. Explore the data and API
- [ ] 2. Ingestion + incremental loads
- [ ] 3. dbt star schema + tests
- [ ] 4. GitHub Actions scheduling
- [ ] 5. SQL analysis + KPIs
- [ ] 6. Statistics: spike detection
- [ ] 7. Text classifier
- [ ] 8. Power BI dashboard
- [ ] 9. Monthly brief, deck, Excel export
- [ ] 10. Port to Databricks
- [ ] 11. Architecture diagram + write-up
