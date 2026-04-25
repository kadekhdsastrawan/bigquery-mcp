# add-use-case

Create a new use case YAML file in the `use_cases/` directory.

## Steps

1. Ask the user for the following if not already provided:
   - **Name** – a human-readable name for the use case
   - **Description** – what data/metrics this use case surfaces
   - **Keywords** – comma-separated terms an LLM might search for
   - **Tables** – fully-qualified BigQuery table IDs used in the query (e.g. `project.dataset.table`)
   - **Parameters** – names and descriptions of any date/filter parameters
   - **Query template** – the BigQuery SQL; use `{param_name}` placeholders matching the parameter names

2. Derive the `id` from the name: lowercase, spaces replaced with underscores, no special characters.

3. Write the file to `use_cases/<id>.yaml` using this schema exactly:

```yaml
id: <id>
name: <Name>
description: >
  <description>
keywords:
  - <keyword1>
  - <keyword2>
tables:
  - project.dataset.table_name
parameters:
  - name: <param_name>
    description: <what this param means>
query_template: |
  SELECT ...
  WHERE date BETWEEN '{param_name}' AND '{other_param}'
```

4. Validate:
   - Every `{placeholder}` in `query_template` has a matching entry in `parameters`.
   - Every table referenced in `query_template` is listed under `tables`.
   - The `id` is unique — grep `use_cases/` for the id before writing.

5. After writing the file, remind the user to run `sync_table_schemas` so any new tables are added to `accessible_tables.yaml` and their schemas are cached in `table_schemas/`.

5. Confirm the file path and show the user the final YAML.
