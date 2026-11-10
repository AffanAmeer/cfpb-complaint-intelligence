-- Company response scorecard: companies other than the credit bureaus with at
-- least 1,000 complaints in the last 12 complete months.
--
-- What "response time" means in this data: CFPB does NOT publish the date a
-- company answered. It publishes a yes/no "timely response" flag (answered within
-- 15 days). So the response-time KPI is the share of closed complaints answered
-- on time. days_to_company in the fact is how long CFPB took to forward the
-- complaint, not the company's answer time, so it is not used here.
--
-- The 1,000 minimum keeps tiny companies out: 1 late answer out of 4 is 75%
-- timely, which says almost nothing.

with base as (

    select
        f.company_key,
        f.is_in_progress,
        f.is_timely_response,
        f.has_monetary_relief,
        f.company_response
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key
    join marts.dim_company as c on c.company_key = f.company_key
    cross join analysis_window as w
    where d.date_day between w.current_start and w.last_month_end
      and not c.is_credit_bureau

),

by_company as (

    select
        company_key,
        count(*)                                                   as complaints,
        count(*) filter (where not is_in_progress)                 as closed,
        count(*) filter (where not is_in_progress and not is_timely_response)
                                                                   as late_answers,
        count(*) filter (where company_response = 'Untimely response')
                                                                   as status_untimely,
        count(*) filter (where has_monetary_relief)                as monetary_relief,
        count(*) filter (where is_in_progress)                     as in_progress
    from base
    group by company_key
    having count(*) >= 1000

)

select
    co.company_name,
    b.complaints,
    b.closed,
    round(100.0 * (b.closed - b.late_answers) / b.closed, 2) as timely_pct_of_closed,
    b.late_answers,
    b.status_untimely,
    round(100.0 * b.monetary_relief / b.closed, 2)           as relief_pct_of_closed,
    round(100.0 * b.in_progress / b.complaints, 1)           as in_progress_pct,
    rank() over (order by (b.closed - b.late_answers) / b.closed) as rank_least_timely
from by_company as b
join marts.dim_company as co on co.company_key = b.company_key
order by rank_least_timely, b.complaints desc;
