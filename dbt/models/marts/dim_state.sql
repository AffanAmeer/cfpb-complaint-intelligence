{# One row per U.S. state, territory or military postal code CFPB uses. #}

select
    state_code,
    state_name,
    area_type
from {{ ref('us_state_codes') }}
