-- Setup, run before every analysis query: the reporting window.
--
-- CFPB publishes a complaint only after the company answers it (or 15 days pass),
-- so the newest weeks are always missing complaints. 00_data_maturity.csv shows it:
-- complaints about companies other than the credit bureaus fall to about half of a
-- normal week two weeks back, and far lower after that. Reporting on those weeks
-- would show a fake fall.
--
-- Rule: a month counts as complete once it ended at least 30 days before the newest
-- complaint in the warehouse. The window then moves forward by itself every day.
--
--   current 12 months = the 12 complete months up to last_month_end
--   prior 12 months   = the 12 months before that (for year-over-year)

create or replace temp view analysis_window as
with as_of as (

    select max(d.date_day) as as_of_date
    from marts.fact_complaints as f
    join marts.dim_date as d on d.date_key = f.date_received_key

),

bounds as (

    select
        as_of_date,
        (date_trunc('month', as_of_date - interval 30 day) - interval 1 day)::date as last_month_end
    from as_of

)

select
    as_of_date,
    last_month_end,
    (date_trunc('month', last_month_end) - interval 11 month)::date as current_start,
    (date_trunc('month', last_month_end) - interval 23 month)::date as prior_start,
    (date_trunc('month', last_month_end) - interval 11 month - interval 1 day)::date as prior_end
from bounds;
