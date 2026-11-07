{#
    By default dbt glues the target schema onto every custom schema
    (main_staging, main_marts). We want the plain names: staging, marts, reference.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
