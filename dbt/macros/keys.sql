{#
    surrogate_key: one stable ID built from one or more columns.
    md5 of the values joined with '|' gives the same key every time the same
    values come in, on DuckDB today and on Databricks later.
#}
{% macro surrogate_key(columns) -%}
    md5(concat_ws('|', {% for col in columns %}coalesce(cast({{ col }} as varchar), '(null)'){% if not loop.last %}, {% endif %}{% endfor %}))
{%- endmacro %}

{#
    date_key: a date as a whole number, e.g. 2026-11-07 -> 20261107.
    Power BI and most warehouses join on these quickly, and they sort correctly.
#}
{% macro date_key(column) -%}
    (year({{ column }}) * 10000 + month({{ column }}) * 100 + day({{ column }}))
{%- endmacro %}
