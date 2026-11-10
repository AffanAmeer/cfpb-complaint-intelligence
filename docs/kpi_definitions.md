# KPI Definitions

Every KPI in `sql/analysis/` follows these definitions. The same rules will be used for the Power BI DAX measures and the monthly brief, so a number means the same thing everywhere.

## Reporting window

| Term | Definition |
| --- | --- |
| As-of date | The newest `date_received` in the warehouse. |
| Complete month | A month that ended at least 30 days before the as-of date. Newer weeks are left out because CFPB publishes most complaints only after the company answers (up to 15 days), so they are still filling in. See `00_data_maturity.csv`: with data as of 2026-11-09, complaints about non-bureau companies in the week of 2026-10-26 were at 46% of a normal week, while bureau complaints were not down at all (112%). |
| Current 12 months | The 12 complete months up to and including the last complete month. |
| Prior 12 months | The 12 months before that. Used for year-over-year (YoY) change. |

The window is worked out in `sql/analysis/_window.sql`, so it moves forward by itself as new data arrives.

## Segments

| Segment | Definition |
| --- | --- |
| Credit bureaus | Equifax, TransUnion and Experian (`dim_company.is_credit_bureau`). About 88% of complaints in the current 12 months. |
| Other companies | Every other company: banks, card issuers, debt collectors, lenders, fintechs. |

Most KPIs are shown for the two segments separately. With the bureaus mixed in, a 20% rise at banks would barely move the total.

## KPIs

| KPI | Formula | Notes |
| --- | --- | --- |
| Complaints | Count of complaints received in the period | By `date_received`. |
| YoY change (counts) | (current - prior) / prior x 100 | A percent change. |
| Change (rates) | current rate - prior rate | In **percentage points**. 99.5% to 99.7% is +0.2 points. |
| Bureau share | Bureau complaints / all complaints x 100 | |
| Timely response rate | Closed complaints answered on time / closed complaints x 100 | "On time" is CFPB's `timely` flag (answered within 15 days). |
| Monetary relief rate | Closed with monetary relief / closed complaints x 100 | Shown for other companies only: the bureaus almost never give money back (0.00% to 0.01%), so it isn't a useful measure for them. |
| In progress share | "In progress" complaints / all complaints x 100 | How unfinished the period still is. |
| Share of segment | Company's complaints / segment's complaints x 100 | |
| Share of product | Issue's complaints / product group's complaints x 100 | |

## Rules behind the formulas

- **Only closed complaints go into response rates.** CFPB marks every "In progress" complaint as timely, and it can't have relief yet. Counting them would push the timely rate up and the relief rate down.
- **There is no company response time in this data.** CFPB publishes whether the answer was timely, not the date of the answer. `days_to_company` in the fact table is how long CFPB took to forward the complaint (the median is 0 days), so it is not used as a response-time KPI.
- **Minimum volume for company rates.** The response scorecard only includes companies with at least 1,000 complaints in the current 12 months. With 4 complaints, one late answer makes a company 75% timely.
- **A complaint count is not a quality score.** Big companies have more customers, and CFPB doesn't publish customer numbers to divide by. Rankings show where the volume is, not who is worst per customer.
- **Products use `product_group`**, CFPB's current 11 products with the old names mapped in dbt, so year-over-year isn't broken by the 2017 and 2023 renames.
