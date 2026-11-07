{#
    One row per company, after merging spellings that only differ by capitals,
    spaces or punctuation ("ONEMAIN FINANCE CORPORATION" = "OneMain Finance Corporation").

    The name shown is the spelling used on the most complaints (ties broken
    alphabetically, so the result is the same on every run).

    This does NOT merge different legal entities of one group (a bank and its
    mortgage arm stay separate). That would need a hand-made mapping.
#}

with spellings as (

    select
        company_key,
        company_match_key,
        company_name,
        count(*)           as complaints,
        min(date_received) as first_seen,
        max(date_received) as last_seen
    from {{ ref('stg_complaints') }}
    group by all

),

ranked as (

    select
        *,
        row_number() over (
            partition by company_key
            order by complaints desc, company_name
        ) as spelling_rank
    from spellings

),

bureaus as (

    select regexp_replace(lower(company_name), '[^a-z0-9]', '', 'g') as company_match_key
    from {{ ref('credit_bureaus') }}

)

select
    r.company_key,
    max(case when r.spelling_rank = 1 then r.company_name end) as company_name,
    count(*)                                                   as name_variants,
    bool_or(b.company_match_key is not null)                   as is_credit_bureau,
    min(r.first_seen)                                          as first_seen,
    max(r.last_seen)                                           as last_seen
from ranked as r
left join bureaus as b
    on b.company_match_key = r.company_match_key
group by r.company_key
