{#
    A calendar table: one row per day, from Jan 1 of the first complaint year to
    Dec 31 of the latest year in the data. Every date in the fact joins to it, so
    Power BI can slice by year, quarter, month or weekday without date maths.
#}

with bounds as (

    select
        make_date(year(min(date_received)), 1, 1)                                     as first_day,
        make_date(year(greatest(max(date_received), max(date_sent_to_company))), 12, 31) as last_day
    from {{ ref('stg_complaints') }}

),

days as (

    select cast(d.generate_series as date) as date_day
    from bounds,
         generate_series(bounds.first_day, bounds.last_day, interval 1 day) as d

)

select
    {{ date_key('date_day') }}               as date_key,
    date_day,
    year(date_day)                           as year,
    quarter(date_day)                        as quarter,
    month(date_day)                          as month,
    monthname(date_day)                      as month_name,
    strftime(date_day, '%Y-%m')              as year_month,
    cast(date_trunc('month', date_day) as date) as month_start,
    cast(date_trunc('week', date_day) as date)  as week_start,
    isodow(date_day)                         as day_of_week,
    dayname(date_day)                        as day_name,
    isodow(date_day) in (6, 7)               as is_weekend
from days
order by date_key
