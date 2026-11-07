{#
    Staging: one row per complaint, cleaned and renamed, still the same grain as raw.
    Rules: trim text, turn blanks into NULL, label "not given" values so they can be
    grouped, standardise state codes, and build the keys the star schema joins on.
    No business logic (product groups, credit bureaus) lives here; that is in the marts.
#}

with source as (

    select * from {{ source('cfpb', 'complaints') }}

),

cleaned as (

    select
        complaint_id,
        date_received,
        date_sent_to_company,
        received_at_utc,
        sent_at_utc,

        trim(product)                                         as product,
        coalesce(nullif(trim(sub_product), ''), '(none)')     as sub_product,
        coalesce(nullif(trim(issue), ''), '(not provided)')   as issue,
        coalesce(nullif(trim(sub_issue), ''), '(none)')       as sub_issue,

        regexp_replace(trim(company), '\s+', ' ', 'g')        as company_name,
        regexp_replace(lower(company), '[^a-z0-9]', '', 'g')  as company_match_key,

        case
            when upper(trim(state)) = 'UNITED STATES MINOR OUTLYING ISLANDS' then 'UM'
            else nullif(upper(trim(state)), '')
        end                                                   as state_code,

        nullif(trim(submitted_via), '')                       as submitted_via,
        nullif(trim(company_response), '')                    as company_response,
        nullif(trim(company_public_response), '')             as company_public_response,
        timely = 'Yes'                                        as is_timely_response,
        coalesce(tags, '') like '%Servicemember%'             as is_servicemember,
        coalesce(tags, '') like '%Older American%'            as is_older_american,

        source                                                as load_source,
        source_as_of_utc,
        last_loaded_at_utc

    from source

)

select
    *,
    {{ surrogate_key(['product', 'sub_product']) }}  as product_key,
    {{ surrogate_key(['issue', 'sub_issue']) }}      as issue_key,
    {{ surrogate_key(['company_match_key']) }}       as company_key,
    {{ date_key('date_received') }}                  as date_received_key,
    {{ date_key('date_sent_to_company') }}           as date_sent_key,
    date_diff('day', date_received, date_sent_to_company) as days_to_company
from cleaned
