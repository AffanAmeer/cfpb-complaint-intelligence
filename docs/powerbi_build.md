# Power BI dashboard: build guide

This guide turns the star schema into a Power BI report. Power BI Desktop runs on Windows, so the build happens on a Waterloo lab machine. The data is produced on the Mac.

## 1. Export the data (Mac)

From the project folder, with the virtual environment active:

```
source .venv/bin/activate
python src/powerbi/export_for_powerbi.py
```

This writes seven CSV files to `data/powerbi/`. The folder is git-ignored because it is large:

| File | Rows | What it is |
| --- | --- | --- |
| `fact_monthly.csv` | about 3.6 million | Complaint counts per month and per dimension key, with the flags needed for rates |
| `dim_date.csv` | 5,844 | One row per day (the date table) |
| `dim_company.csv` | 8,200 | One row per company, with `is_credit_bureau` |
| `dim_product.csv` | 127 | Product + sub-product, with the stable `product_group` |
| `dim_issue.csv` | 442 | Issue + sub-issue |
| `dim_state.csv` | 63 | State and territory codes |
| `reporting_window.csv` | 1 | The complete-month window, the same rule as the SQL KPIs |

`fact_monthly.csv` is about 580 MB. Copy the whole `data/powerbi/` folder to the lab machine with a USB drive or OneDrive.

## 2. Load the data (Power BI Desktop, Windows)

For each file: **Home > Get data > Text/CSV**, pick the file, then **Transform data**.

Before closing Power Query, check these column types:

- `month_start`, `date_day`, `week_start`: Date
- `date_key`, `complaints`, `year`, `quarter`, `month`: Whole number
- `is_timely_response`, `is_in_progress`, `has_monetary_relief`, `is_servicemember`, `is_older_american`, `is_credit_bureau`, `is_weekend`: True/False
- All `*_key` columns and `state_code` and `company_response`: Text

Power Query records each step, so the Mac export can be re-run and the lab refresh picks up the change.

## 3. Build the model

Use **Model view**. Create these relationships (all many-to-one, single direction, from the table with many rows to the dimension):

| From (many) | To (one) | Column |
| --- | --- | --- |
| fact_monthly | dim_company | company_key |
| fact_monthly | dim_product | product_key |
| fact_monthly | dim_issue | issue_key |
| fact_monthly | dim_state | state_code |
| fact_monthly | dim_date | month_start to date_day |

Then select `dim_date`, and choose **Table tools > Mark as date table** on the `date_day` column. Time intelligence functions such as `SAMEPERIODLASTYEAR` need this.

## 4. Measures (DAX)

Create a table called `_Measures` (Home > Enter data, then delete the data) so the measures are easy to find. Then add each measure below.

```
Complaints = SUM ( fact_monthly[complaints] )
```

```
Closed complaints =
CALCULATE ( [Complaints], fact_monthly[is_in_progress] = FALSE () )
```

```
Timely rate % =
DIVIDE (
    CALCULATE ( [Complaints], fact_monthly[is_timely_response] = TRUE (), fact_monthly[is_in_progress] = FALSE () ),
    [Closed complaints]
) * 100
```

```
Relief rate % (other companies) =
DIVIDE (
    CALCULATE ( [Complaints], fact_monthly[has_monetary_relief] = TRUE (), dim_company[is_credit_bureau] = FALSE () ),
    CALCULATE ( [Closed complaints], dim_company[is_credit_bureau] = FALSE () )
) * 100
```

```
Bureau share % =
DIVIDE ( CALCULATE ( [Complaints], dim_company[is_credit_bureau] = TRUE () ), [Complaints] ) * 100
```

```
Complaints prior year =
CALCULATE ( [Complaints], SAMEPERIODLASTYEAR ( dim_date[date_day] ) )
```

```
YoY change % =
VAR prior = [Complaints prior year]
RETURN DIVIDE ( [Complaints] - prior, prior ) * 100
```

```
Last complete month end =
MAX ( reporting_window[last_month_end] )
```

```
Complaints (complete months) =
CALCULATE ( [Complaints], dim_date[date_day] <= [Last complete month end] )
```

Why these rules: the rates use closed complaints only, the bureaus and other companies are shown separately, and the newest weeks are left out because CFPB is still receiving answers for them. These match `docs/kpi_definitions.md`, so a number on the dashboard equals the same number in the SQL output.

Use `reporting_window` as a filter on the report page so that visuals show complete months by default.

## 5. Pages to build

1. **Overview**: cards for Complaints, YoY change %, Bureau share %, Timely rate %, Relief rate % (other companies). Line chart of complaints by month, split by bureau vs other companies.
2. **Products**: bar chart of complaints by `product_group`, with YoY change % next to each bar.
3. **Companies**: top 15 other companies by complaints, with timely rate. Use a minimum-volume filter of 1,000 complaints in the current 12 months, as in the KPI rules.
4. **Issues**: top issues within a selected product (use a slicer on `product_group`).
5. **Map**: complaints by `state_code` (a filled map, using the state codes as the location).

Each page should have a title, a one-line subtitle that says the data date, and a slicer for the segment (bureaus, other companies, or both).

## 6. Check the numbers

Each card should match a CSV in `reports/kpis/`. For example, the Overview card for YoY change should equal `reports/kpis/01_headline_kpis.csv`. If a number is different, the relationship or the filter is wrong, not the data.

## 7. Save

Save the report as `powerbi/complaints_dashboard.pbix` on the lab machine. Copy it back to the Mac and place it in the repo's `powerbi/` folder, so it lives with the project. The `.pbix` file can be large, so check its size before committing it.
