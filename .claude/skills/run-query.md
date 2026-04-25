# run-query

Execute a BigQuery query using the MCP server's use-case workflow: find a relevant use case, fill in parameters, run the query, and optionally deliver results by email.

## Steps

1. **Understand the request** – identify what data the user wants and any date range or filter constraints.

2. **Gather context from use cases**
   - Call `mcp__bigquery-mcp__search_use_cases` with a natural-language description of the request.
   - If a match is found, call `mcp__bigquery-mcp__get_use_case` to retrieve the template — use it as a pattern reference (metric definitions, grouping logic, filter idioms), not necessarily verbatim.

3. **Gather schema from tables**
   - Call `mcp__bigquery-mcp__list_tables` to see what tables are available.
   - Call `mcp__bigquery-mcp__get_table_schema` for any table relevant to the request to get live column names, types, and descriptions.
   - Use the schema to construct or adapt the query precisely to what columns actually exist.

4. **Build the query**
   - Compose SQL from the schema knowledge (step 3) informed by use case patterns (step 2).
   - Dates must be in `YYYY-MM-DD` format unless the schema indicates otherwise.
   - Only query tables listed in `accessible_tables.yaml`.

4. **Execute**
   - For preview (≤1000 rows): call `mcp__bigquery-mcp__execute_query`.
   - For full export: call `mcp__bigquery-mcp__generate_csv_from_query`. Note the returned `csv_path`.

5. **Email (optional)**
   - If the user wants the results emailed, call `mcp__bigquery-mcp__send_csv_via_email` with the `csv_path` and recipient address.
   - Default subject: `"<use case name> – <start_date> to <end_date>"`.

6. **Report back** – summarise row count, columns returned, and (if emailed) delivery status.
