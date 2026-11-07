{#
    One row per issue + sub-issue (about 440 rows).
    Issue names also changed in 2017 and 2023 (e.g. "Incorrect information on credit report"
    became "Incorrect information on your report"). We keep CFPB's names as they are for now;
    grouping issues across eras is a later step, once Phase 5 shows which issues matter.
#}

select
    issue_key,
    issue,
    sub_issue,
    min(date_received) as first_seen,
    max(date_received) as last_seen
from {{ ref('stg_complaints') }}
group by all
