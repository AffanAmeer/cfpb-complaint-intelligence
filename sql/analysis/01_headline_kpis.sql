-- Headline KPIs: the last 12 complete months against the 12 months before.
--
-- One row per KPI, so it reads like a scorecard.
-- Rates about the company's answer (timely, monetary relief) only count CLOSED
-- complaints: an "In progress" complaint is always marked timely and can't have
-- relief yet, so including it would flatter the timely rate and dilute relief.

with base as (

    select
        case when d.date_day >= w.current_start then 'current' else 'prior' end as period,
        c.is_credit_bureau,
        f.is_in_progress,
        f.is_timely_response,
        f.has_monetary_relief
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key
    join marts.dim_company as c on c.company_key = f.company_key
    cross join analysis_window as w
    where d.date_day between w.prior_start and w.last_month_end

),

by_period as (

    select
        period,
        count(*)                                        as complaints_all,
        count(*) filter (where is_credit_bureau)        as complaints_bureaus,
        count(*) filter (where not is_credit_bureau)    as complaints_other,
        100.0 * count(*) filter (where is_credit_bureau) / count(*)
                                                        as bureau_share_pct,
        100.0 * count(*) filter (where is_timely_response and not is_in_progress)
              / count(*) filter (where not is_in_progress)
                                                        as timely_pct_of_closed,
        100.0 * count(*) filter (where has_monetary_relief and not is_credit_bureau)
              / count(*) filter (where not is_in_progress and not is_credit_bureau)
                                                        as other_relief_pct_of_closed,
        100.0 * count(*) filter (where is_in_progress) / count(*)
                                                        as in_progress_pct
    from base
    group by period

),

long as (

    -- UNPIVOT turns the columns above into rows: one row per (period, kpi).
    unpivot by_period
    on complaints_all, complaints_bureaus, complaints_other, bureau_share_pct,
       timely_pct_of_closed, other_relief_pct_of_closed, in_progress_pct
    into name kpi value value

)

select
    l.kpi,
    max(w.prior_start) || ' to ' || max(w.prior_end)        as prior_period,
    max(w.current_start) || ' to ' || max(w.last_month_end) as current_period,
    round(max(l.value) filter (where l.period = 'prior'), 2)   as prior_value,
    round(max(l.value) filter (where l.period = 'current'), 2) as current_value,
    -- Counts get a % change. Rates get a change in percentage points instead,
    -- because "timely went from 99.5% to 99.7%" is +0.2 points, not +0.2%.
    case when l.kpi like 'complaints%' then 'pct_change' else 'points_change' end as change_type,
    round(case
        when l.kpi like 'complaints%'
            then 100.0 * (max(l.value) filter (where l.period = 'current')
                        - max(l.value) filter (where l.period = 'prior'))
                       / max(l.value) filter (where l.period = 'prior')
        else max(l.value) filter (where l.period = 'current')
           - max(l.value) filter (where l.period = 'prior')
    end, 2) as change
from long as l
cross join analysis_window as w
group by l.kpi
order by l.kpi like 'complaints%' desc, l.kpi;
