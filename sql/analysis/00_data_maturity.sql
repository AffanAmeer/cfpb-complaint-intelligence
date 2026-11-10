-- Why the newest weeks are left out of every KPI.
--
-- Weekly complaints for the last 16 weeks, split into the three credit bureaus and
-- everyone else, each compared with that group's average week over the 8 weeks
-- before the window. A week far below 100% has not been fully published yet.

with weekly as (

    select
        d.week_start,
        count(*) filter (where c.is_credit_bureau)     as bureau_complaints,
        count(*) filter (where not c.is_credit_bureau) as other_complaints
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key
    join marts.dim_company as c on c.company_key = f.company_key
    cross join analysis_window as w
    where d.week_start >= w.as_of_date - interval 24 week
    group by d.week_start

),

numbered as (

    select
        *,
        row_number() over (order by week_start desc) as weeks_back
    from weekly

),

baseline as (

    select
        avg(bureau_complaints) as bureau_baseline,
        avg(other_complaints)  as other_baseline
    from numbered
    where weeks_back between 17 and 24

)

select
    n.week_start,
    n.bureau_complaints,
    round(100.0 * n.bureau_complaints / b.bureau_baseline, 0) as bureau_pct_of_baseline,
    n.other_complaints,
    round(100.0 * n.other_complaints / b.other_baseline, 0)   as other_pct_of_baseline,
    n.week_start > w.last_month_end                            as left_out_of_kpis
from numbered as n
cross join baseline as b
cross join analysis_window as w
where n.weeks_back <= 16
order by n.week_start;
