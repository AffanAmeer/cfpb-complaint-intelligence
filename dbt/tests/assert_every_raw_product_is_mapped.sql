-- Every product name in the raw data must appear in the product_group_map seed.
-- If CFPB adds or renames a product, this fails and tells us which one to map.
select distinct trim(c.product) as unmapped_product
from {{ source('cfpb', 'complaints') }} as c
left join {{ ref('product_group_map') }} as m
    on m.product = trim(c.product)
where m.product is null
