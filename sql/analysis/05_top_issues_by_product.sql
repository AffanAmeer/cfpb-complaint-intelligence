-- The top 3 issues inside each product group, last 12 complete months.
--
-- "Worst issues by product": what people complain ABOUT, not just how many.
-- QUALIFY filters on a window function, the way HAVING filters on an aggregate.
-- Issue names were renamed in 2017 and 2023, but a 12-month window sits inside the
-- current naming, so no mapping is needed here (it would be for a long trend).

with base as (

    select
        p.product_group,
        i.issue,
        c.is_credit_bureau
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key
    join marts.dim_product as p on p.product_key = f.product_key
    join marts.dim_issue as i on i.issue_key = f.issue_key
    join marts.dim_company as c on c.company_key = f.company_key
    cross join analysis_window as w
    where d.date_day between w.current_start and w.last_month_end

),

by_issue as (

    select
        product_group,
        issue,
        count(*)                                 as complaints,
        count(*) filter (where is_credit_bureau) as bureau_complaints
    from base
    group by product_group, issue

)

select
    product_group,
    rank() over (partition by product_group order by complaints desc) as issue_rank,
    issue,
    complaints,
    round(100.0 * complaints / sum(complaints) over (partition by product_group), 1)
                                                         as share_of_product_pct,
    round(100.0 * bureau_complaints / complaints, 1)      as bureau_share_pct
from by_issue
qualify issue_rank <= 3
order by sum(complaints) over (partition by product_group) desc, issue_rank;
