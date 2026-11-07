{#
    The fact table: one row per complaint (about 19M rows).
    It holds the keys to each dimension plus the facts about the complaint itself.

    Low-variety text fields (how it was submitted, the company's response) stay here
    as "degenerate dimensions": a separate table for 6-9 values adds a join and no value.
#}

select
    complaint_id,

    date_received_key,
    date_sent_key,
    product_key,
    issue_key,
    company_key,
    state_code,

    submitted_via,
    company_response,
    company_public_response,
    is_timely_response,
    company_response = 'In progress'                     as is_in_progress,
    company_response = 'Closed with monetary relief'     as has_monetary_relief,
    is_servicemember,
    is_older_american,

    days_to_company,
    days_to_company < 0                                  as is_sent_before_received,

    source_as_of_utc
from {{ ref('stg_complaints') }}
