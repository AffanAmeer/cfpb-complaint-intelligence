-- The fact table must have exactly one row for every raw complaint.
-- Returns a row (= test fails) if any complaint was lost or duplicated on the way.
with counts as (
    select
        (select count(*) from {{ source('cfpb', 'complaints') }}) as raw_rows,
        (select count(*) from {{ ref('fact_complaints') }})        as fact_rows
)
select * from counts
where raw_rows != fact_rows
