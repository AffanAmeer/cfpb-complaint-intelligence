# Data quality findings (Phase 1)

Checked on 2026-11-06 using the CFPB complaint API. Volume numbers come from exact monthly counts covering all 18,965,764 complaints. Everything else comes from a sample of 100 complaints per month (17,900 rows), taken from the last day or two of each month, so it shows formats and gaps but not true shares. Details are in `notebooks/01_explore_data.ipynb`.

## API behaviour

- The API docs say `date_received_max` excludes the end date, but it actually includes it (Oct 1 to Oct 1 returns 27,811 complaints). Using the 1st of the next month as the end date double-counted 501,981 complaints, so each month now ends on its last day, and the monthly counts are checked against the API total.
- `format=json` was retired in July 2026, pages max out at 100 rows, and complaint narratives were removed in September 2026.

## What the data looks like

1. **Volume:** complaints grew from 2,536 in December 2011 to 736,335 in October 2026, so any trend analysis has to deal with a huge growth curve rather than a stable baseline.
2. **Missing values:** `tags` is empty about 89% of the time, but that just means "no tag", not missing data.
3. **Missing by year:** `sub_product`, `sub_issue` and `company_public_response` are mostly empty in the early years and filled in later, so gaps depend on the era, not on bad records.
4. **Keys:** `complaint_id` is unique and always digits, but it arrives as text, so it needs casting to a number before sorting or joining.
5. **Dates:** until mid-2014, `date_sent_to_company` was stored as midnight Eastern time with no real clock time, which makes 507 sampled complaints look like they were sent before they were received.
6. **Products:** product names were renamed in 2017 and again in 2023 (for example "Bank account or service" became "Checking or savings account"), so year-over-year comparisons need a mapping to stable product groups.
7. **Company response:** the response categories also changed over time ("Closed with relief" only appears in 2011-2012), and recent complaints can still be "In progress", which means rows get updated after we first load them.
8. **Geography:** `state` is empty for about 1% of the sample and includes territories and military codes (PR, AP, AE) plus at least one full name instead of a code, and many ZIP codes are partly or fully masked (`606XX`, `XXXXX`).
9. **Companies:** the sample has 1,118 different companies with inconsistent capitalisation in their names, and the three credit bureaus appear most often.
