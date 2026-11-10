-- Which products are growing? Year-over-year by product group.
--
-- Uses product_group (CFPB's current 11 products, with old names mapped in dbt),
-- so the comparison is not broken by CFPB's 2017 and 2023 renames.
-- Shown for all companies and for companies other than the credit bureaus.

with base as (

    select
        p.product_group,
        c.is_credit_bureau,
        case when d.date_day >= w.current_start then 'current' else 'prior' end as period
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key
    join marts.dim_product as p on p.product_key = f.product_key
    join marts.dim_company as c on c.company_key = f.company_key
    cross join analysis_window as w
    where d.date_day between w.prior_start and w.last_month_end

),

counts as (

    select
        product_group,
        count(*) filter (where period = 'prior')                          as all_prior,
        count(*) filter (where period = 'current')                        as all_current,
        count(*) filter (where period = 'prior' and not is_credit_bureau)   as other_prior,
        count(*) filter (where period = 'current' and not is_credit_bureau) as other_current
    from base
    group by product_group

)

select
    product_group,
    all_prior,
    all_current,
    round(100.0 * (all_current - all_prior) / all_prior, 1)       as all_yoy_pct,
    other_prior,
    other_current,
    round(100.0 * (other_current - other_prior) / other_prior, 1) as other_yoy_pct,
    -- Share of all "other company" complaints this year. sum() over () = the grand total.
    round(100.0 * other_current / sum(other_current) over (), 1)  as other_share_pct
from counts
order by other_current desc;
