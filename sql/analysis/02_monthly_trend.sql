-- Monthly complaint volume, every complete month since Dec 2011.
--
-- Split into the three credit bureaus and all other companies, because the bureaus
-- are about 80% of recent volume and would hide any change elsewhere.
-- Window functions add month-over-month change, year-over-year change and a
-- 3-month rolling average (which smooths out short months like February).

with monthly as (

    select
        d.month_start,
        count(*)                                     as complaints_all,
        count(*) filter (where c.is_credit_bureau)     as complaints_bureaus,
        count(*) filter (where not c.is_credit_bureau) as complaints_other
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key
    join marts.dim_company as c on c.company_key = f.company_key
    cross join analysis_window as w
    where d.date_day <= w.last_month_end
    group by d.month_start

)

select
    month_start,
    complaints_all,
    complaints_bureaus,
    complaints_other,
    round(100.0 * complaints_bureaus / complaints_all, 1) as bureau_share_pct,

    -- LAG(x, 1) = the value one row back (last month); LAG(x, 12) = same month last year.
    -- This works because every month has at least one complaint, so no month is missing.
    round(100.0 * (complaints_other - lag(complaints_other, 1) over by_month)
                / lag(complaints_other, 1) over by_month, 1)  as other_mom_pct,
    round(100.0 * (complaints_other - lag(complaints_other, 12) over by_month)
                / lag(complaints_other, 12) over by_month, 1) as other_yoy_pct,
    round(100.0 * (complaints_all - lag(complaints_all, 12) over by_month)
                / lag(complaints_all, 12) over by_month, 1)   as all_yoy_pct,

    -- A rolling average: this month and the 2 before it.
    round(avg(complaints_other) over (by_month rows between 2 preceding and current row), 0)
                                                           as other_rolling_3m_avg
from monthly
window by_month as (order by month_start)
order by month_start;
