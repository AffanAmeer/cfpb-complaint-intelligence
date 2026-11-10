-- Weekly complaint counts, the input for spike detection (src/stats/run_spike_detection.py).
--
-- One row per week x credit-bureau flag x product group x company.
-- Python adds these rows up into the series it tests (all non-bureau companies,
-- each product group, each big company).
--
-- Why weeks and not days or months?
--   * Days swing with the day of the week (a Sunday has about 40% of a Tuesday's
--     complaints), so a daily series is mostly weekday noise.
--   * Months give only 12 points a year, too few for a 12-point rolling baseline
--     that still reacts quickly.
--   * A week always holds each weekday once, so the weekday pattern cancels out.
--
-- Weeks start on Monday (dim_date.week_start).
--
-- Only complete weeks: a week must have ended at least 30 days before the newest
-- complaint in the warehouse. This is the same reporting-lag rule as the KPI
-- queries (sql/analysis/_window.sql): CFPB publishes a complaint only after the
-- company answers, so the newest weeks are always short and would look like a drop.
--
-- Weeks start from 2014-08-04, after the last product type was added to the
-- database (prepaid cards and debt management, July 2014). Earlier jumps are
-- products being added, not spikes.

with as_of as (

    select max(d.date_day) as as_of_date
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key

)

select
    d.week_start,
    c.is_credit_bureau,
    p.product_group_short as product_group,
    c.company_name,
    count(*) as complaints
from marts.fact_complaints as f
join marts.dim_date as d on d.date_key = f.date_received_key
join marts.dim_company as c on c.company_key = f.company_key
join marts.dim_product as p on p.product_key = f.product_key
cross join as_of
where d.week_start >= date '2014-08-04'
  and d.week_start + interval 6 day <= as_of.as_of_date - interval 30 day
group by all
order by d.week_start
