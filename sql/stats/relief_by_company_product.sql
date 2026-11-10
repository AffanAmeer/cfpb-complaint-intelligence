-- Closed complaints and monetary relief per company and product group, last 12
-- complete months, companies other than the credit bureaus.
--
-- Input for the relief-rate test in src/stats/significance_tests.py. Phase 5 found
-- that Bank of America gives monetary relief on about 25% of closed complaints and
-- Capital One on about 6%, but warned that the two have different product mixes.
-- This table lets us compare them inside one product.
--
-- Needs the analysis_window view: run sql/analysis/_window.sql first.
-- Relief rates use closed complaints only, as in the KPI definitions.

select
    c.company_name,
    p.product_group_short as product_group,
    count(*)                                   as closed,
    count(*) filter (where f.has_monetary_relief) as monetary_relief
from marts.fact_complaints as f
join marts.dim_date as d on d.date_key = f.date_received_key
join marts.dim_company as c on c.company_key = f.company_key
join marts.dim_product as p on p.product_key = f.product_key
cross join analysis_window as w
where d.date_day between w.current_start and w.last_month_end
  and not c.is_credit_bureau
  and not f.is_in_progress
group by all
