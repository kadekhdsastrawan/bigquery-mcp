# add-use-case

Create a new use case YAML file in the `use_cases/` directory.

## Steps

1. Ask the user for the following if not already provided:
   - **Name** – a human-readable name for the use case
   - **Description** – what data/metrics this use case surfaces
   - **Keywords** – comma-separated terms an LLM might search for
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
parameters:
  - name: <param_name>
    description: <what this param means>
query_template: |
  SELECT ...
  WHERE date BETWEEN '{param_name}' AND '{other_param}'
```

4. Validate:
   - Every `{placeholder}` in `query_template` has a matching entry in `parameters`.
   - The `id` is unique — grep `use_cases/` for the id before writing.

5. Confirm the file path and show the user the final YAML.
