{#
    One row per product + sub-product as CFPB wrote it (about 127 rows).

    CFPB renamed its products in April 2017 and again in August 2023, so the same
    kind of complaint has up to three different product names over time. The
    product_group_map seed maps every old name onto CFPB's current (2023) product
    list, which gives one stable product_group to compare years with.

    Matching works in two steps:
      1. an exact match on product + sub_product (used where CFPB split a product,
         e.g. "Credit card or prepaid card" -> Credit card OR Prepaid card), then
      2. a default for the product (seed rows with an empty sub_product).
#}

with combos as (

    select
        product_key,
        product,
        sub_product,
        min(date_received) as first_seen,
        max(date_received) as last_seen
    from {{ ref('stg_complaints') }}
    group by all

),

product_map as (

    select * from {{ ref('product_group_map') }}

)

select
    c.product_key,
    c.product,
    c.sub_product,
    coalesce(exact_match.product_group, default_match.product_group)             as product_group,
    coalesce(exact_match.product_group_short, default_match.product_group_short) as product_group_short,
    c.first_seen,
    c.last_seen
from combos as c
left join product_map as exact_match
    on exact_match.product = c.product
   and exact_match.sub_product = c.sub_product
left join product_map as default_match
    on default_match.product = c.product
   and default_match.sub_product is null
