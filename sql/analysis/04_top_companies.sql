-- Most-complained-about companies in the last 12 complete months.
--
-- Ranked separately inside two segments (credit bureaus, all other companies),
-- because the 3 bureaus each get more complaints than every other company combined.
-- A raw count is NOT a quality score: big banks have more customers, and the CFPB
-- data has no customer counts to divide by. Read this as "where the volume is".

with base as (

    select
        f.company_key,
        case when c.is_credit_bureau then 'Credit bureau' else 'Other company' end as segment,
        case when d.date_day >= w.current_start then 'current' else 'prior' end  as period,
        f.is_in_progress,
        f.is_timely_response,
        f.has_monetary_relief
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key
    join marts.dim_company as c on c.company_key = f.company_key
    cross join analysis_window as w
    where d.date_day between w.prior_start and w.last_month_end

),

by_company as (

    select
        company_key,
        segment,
        count(*) filter (where period = 'current') as complaints_current,
        count(*) filter (where period = 'prior')   as complaints_prior,
        count(*) filter (where period = 'current' and not is_in_progress) as closed_current,
        count(*) filter (where period = 'current' and not is_in_progress and is_timely_response)
                                                   as timely_current,
        count(*) filter (where period = 'current' and has_monetary_relief) as relief_current
    from base
    group by company_key, segment

),

ranked as (

    select
        *,
        rank() over (partition by segment order by complaints_current desc) as rank_current,
        case when complaints_prior > 0
             then rank() over (partition by segment order by complaints_prior desc)
        end                                                                as rank_prior,
        100.0 * complaints_current / sum(complaints_current) over (partition by segment)
                                                                           as share_of_segment_pct
    from by_company

)

select
    r.segment,
    r.rank_current,
    r.rank_prior,
    co.company_name,
    r.complaints_current,
    r.complaints_prior,
    round(100.0 * (r.complaints_current - r.complaints_prior) / nullif(r.complaints_prior, 0), 1)
                                                         as yoy_pct,
    round(r.share_of_segment_pct, 2)                     as share_of_segment_pct,
    round(100.0 * r.timely_current / nullif(r.closed_current, 0), 2) as timely_pct_of_closed,
    round(100.0 * r.relief_current / nullif(r.closed_current, 0), 2) as relief_pct_of_closed
from ranked as r
join marts.dim_company as co on co.company_key = r.company_key
where r.rank_current <= 15
order by r.segment, r.rank_current;
