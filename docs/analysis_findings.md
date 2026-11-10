# Analysis Findings (Phase 5: SQL KPIs)

**Data as of 2026-11-09** (19,028,339 complaints, reconciled exactly with the CFPB API). Current 12 months = Oct 2025 to Sep 2026. Prior 12 months = Oct 2024 to Sep 2025. October 2026 is left out because it is not fully published yet (see [KPI definitions](kpi_definitions.md)).

Every number below comes from the CSVs in `reports/kpis/`, produced by `python src/analysis/run_kpis.py`. Those CSVs are a snapshot: the window moves forward each day, and CFPB keeps updating old complaints, so a later run will give slightly different numbers.

This is U.S. data. Complaints are filed by people who chose to complain, so they show where problems are reported, not how common problems are across all customers.

## 1. Complaints are up 46%, but mostly at the credit bureaus

| | Prior 12 months | Current 12 months | Change |
| --- | ---: | ---: | ---: |
| All complaints | 4,800,962 | 7,010,093 | +46.0% |
| Credit bureaus | 4,101,104 | 6,148,282 | +49.9% |
| Other companies | 699,858 | 861,811 | +23.1% |
| Bureau share | 85.4% | 87.7% | +2.3 points |

The three bureaus are now 87.7% of all complaints. Complaints about everyone else grew too, by 23.1%, which is the more useful number for a bank.

## 2. The growth at other companies is slowing down

Year-over-year change in non-bureau complaints, by month (`02_monthly_trend.csv`):

| Month | Dec 2025 | Mar 2026 | Jun 2026 | Jul 2026 | Aug 2026 | Sep 2026 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| YoY change | +68.8% | +46.6% | +30.0% | +14.3% | +13.5% | +11.5% |

The 3-month rolling average peaked at 79,454 a month (Jan to Mar 2026) and was 67,710 by Sep 2026. January 2026 shows -33.4% YoY, but that is a base effect: January 2025 had an unusual jump (Block, Inc. alone had 31,327 complaints that month, and Early Warning Services 17,146; a one-off query, not in the CSVs). Phase 6 will test spikes like that properly.

## 3. Debt collection is now the biggest non-bureau product

Non-bureau complaints by product group (`03_product_yoy.csv`):

| Product group | Prior | Current | YoY | Share now |
| --- | ---: | ---: | ---: | ---: |
| Debt collection | 181,180 | 292,812 | +61.6% | 34.0% |
| Credit reporting (non-bureau companies) | 214,678 | 244,819 | +14.0% | 28.4% |
| Credit card | 63,711 | 88,997 | +39.7% | 10.3% |
| Checking or savings | 78,324 | 88,783 | +13.4% | 10.3% |
| Money transfer / virtual currency | 79,232 | 39,533 | -50.1% | 4.6% |
| Mortgage | 22,993 | 33,509 | +45.7% | 3.9% |
| Payday / personal loan | 11,533 | 18,556 | +60.9% | 2.2% |

Money transfer halved because the prior year included the January 2025 jump. Student loans (-3.5%) and prepaid cards (+0.4%) were flat. Everything else grew.

## 4. Who gets the most complaints (other companies)

From `04_top_companies.csv`. These are counts, not rates per customer, so big companies rank high just by being big.

- **LexisNexis** went from 16,208 to 34,987 complaints (+115.9%) and from #11 to #1. Almost all of it is credit reporting (34,890), so it behaves like a fourth credit bureau.
- **CL Holdings LLC** went from #14 to #3 (+113.7%), mostly debt collection (24,048).
- **Capital One** is #2 (34,790, +9.0%). The other big banks rose 18% to 40%: JPMorgan Chase +18.4%, Bank of America +40.4%, Citibank +34.1%, Wells Fargo +30.0%.
- **Block, Inc.** fell from #1 (45,360) to #13 (15,995), again the January 2025 effect.
- **Chime** (+123.2%) and **PayPal** (+103.6%) more than doubled.

## 5. The top issue inside each product

From `05_top_issues_by_product.csv`, all companies, current 12 months:

| Product group | Top issue | Share of the product |
| --- | --- | ---: |
| Credit reporting | Incorrect information on your report | 59.7% |
| Debt collection | Attempts to collect debt not owed | 43.3% |
| Checking or savings | Managing an account | 58.0% |
| Mortgage | Trouble during payment process | 48.6% |
| Credit card | Problem with a purchase shown on your statement | 32.1% |
| Money transfer | Fraud or scam | 28.8% |
| Student loan | Dealing with your lender or servicer | 57.1% |

## 6. Response KPIs: almost everyone is on time, with a few clear exceptions

- The timely response rate is flat: 99.57% to 99.55% of closed complaints (-0.02 points).
- Of the 131 non-bureau companies with at least 1,000 complaints, 112 answer at least 99% on time. The median is 99.96%.
- The exceptions are mostly student loans and collections. **MOHELA** answered 27.76% of 8,551 closed complaints on time. **Shellpoint** (mortgage servicing) answered 82.49%. Two names, "Servicer under contract with Federal Student Aid" and Rent Recovery Solutions, show 0%, because every one of their complaints has the status "Untimely response". That looks like a pattern in how these complaints are handled or recorded, not just slow answers, so it should be checked before anyone draws a conclusion.
- Monetary relief at non-bureau companies rose from 3.58% to 3.92% of closed complaints (+0.34 points). 1.89% of the current period is still in progress, so this could still move.
- Relief rates differ a lot between big banks: Bank of America 24.81%, Citibank 19.77%, PayPal 19.32%, but Capital One 5.68% and JPMorgan Chase 7.63%. That does **not** prove one bank is more generous. The banks have different product mixes (a disputed card purchase is easier to refund than a mortgage problem), and companies may label outcomes differently. Comparing within one product would be the fair test.

## What a bank should take from this

1. Report the bureaus separately. Mixed in, they hide a 23% rise at everyone else.
2. Debt collection and "debt not owed" disputes are the biggest and fastest-growing problem outside the bureaus.
3. Growth at banks and fintechs is slowing (from +69% YoY in Dec 2025 to +11.5% in Sep 2026), but volumes are still well above a year ago.
4. On-time answers are nearly universal, so the timely rate barely separates companies. Relief rates and complaint growth are more useful, compared within the same product.
