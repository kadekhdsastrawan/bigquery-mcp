"""
BigQuery MCP Server

Workflow:
  1. User creates a prompt
  2. LLM searches relevant use cases to cover the needs
  3. LLM constructs a query based on the use case template
  4. LLM generates a CSV from query results
  5. LLM sends the CSV to the user's email
"""

import csv
import io
import json
import os
import smtplib
import threading
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.cloud import bigquery
import google.auth
from mcp.server.fastmcp import FastMCP

load_dotenv()

mcp = FastMCP("bigquery-mcp")

# ---------------------------------------------------------------------------
# Credential & Client caching
# Uses Application Default Credentials (ADC): honours GOOGLE_APPLICATION_CREDENTIALS
# if set, otherwise falls back to `gcloud auth application-default login`,
# Workload Identity, or the metadata server — whichever is available.
# Credentials are resolved once at server start and cached; the BigQuery client
# refreshes the access token automatically when it approaches expiry.
# ---------------------------------------------------------------------------

_CLIENT_LOCK = threading.Lock()
_bq_client: bigquery.Client | None = None

_BQ_SCOPES = [
    "https://www.googleapis.com/auth/bigquery",
    "https://www.googleapis.com/auth/cloud-platform",
]


def _build_credentials():
    """Resolve and return Application Default Credentials.

    ADC resolution order (handled automatically by google-auth):
      1. GOOGLE_APPLICATION_CREDENTIALS env var (service account JSON or
         external-credentials file)
      2. gcloud user credentials  (`gcloud auth application-default login`)
      3. Workload Identity / metadata server (GCE, GKE, Cloud Run, etc.)
    """
    creds, project = google.auth.default(scopes=_BQ_SCOPES)
    # Pre-warm the token so the first tool call has no auth latency
    if not creds.valid:
        creds.refresh(Request())
    return creds, project


def get_bq_client() -> bigquery.Client:
    """Return a cached BigQuery client.  Thread-safe; builds on first call only."""
    global _bq_client
    with _CLIENT_LOCK:
        if _bq_client is None:
            creds, detected_project = _build_credentials()
            project_id = os.environ.get("GCP_PROJECT_ID") or detected_project
            _bq_client = bigquery.Client(credentials=creds, project=project_id)
    return _bq_client


# ---------------------------------------------------------------------------
# Use-case helpers
# ---------------------------------------------------------------------------

USE_CASES_DIR = Path(__file__).parent / "use_cases"
ACCESSIBLE_TABLES_FILE = Path(__file__).parent / "accessible_tables.yaml"
TABLE_SCHEMAS_DIR = Path(__file__).parent / "table_schemas"


def _load_accessible_tables() -> list[str]:
    if not ACCESSIBLE_TABLES_FILE.exists():
        return []
    with open(ACCESSIBLE_TABLES_FILE, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    return data.get("tables", []) if data else []


def _load_use_cases() -> list[dict]:
    use_cases: list[dict] = []
    if USE_CASES_DIR.exists():
        for path in sorted(USE_CASES_DIR.glob("*.yaml")):
            with open(path, encoding="utf-8") as fh:
                uc = yaml.safe_load(fh)
                if uc:
                    use_cases.append(uc)
    return use_cases


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_use_cases() -> str:
    """List all available use cases with their IDs, names, descriptions, and keywords."""
    use_cases = _load_use_cases()
    if not use_cases:
        return "No use cases found. Add YAML files to the use_cases/ directory."
    summary = [
        {
            "id": uc.get("id"),
            "name": uc.get("name"),
            "description": uc.get("description"),
            "keywords": uc.get("keywords", []),
            "parameters": [p.get("name") for p in uc.get("parameters", [])],
        }
        for uc in use_cases
    ]
    return json.dumps(summary, indent=2)


@mcp.tool()
def get_use_case(use_case_id: str) -> str:
    """Return full details of a specific use case, including the query template.

    Args:
        use_case_id: The unique identifier of the use case (e.g. 'daily_sales_report').
    """
    for uc in _load_use_cases():
        if uc.get("id") == use_case_id:
            return json.dumps(uc, indent=2)
    return f"Use case '{use_case_id}' not found."


@mcp.tool()
def search_use_cases(query: str) -> str:
    """Search for relevant use cases by matching a natural language query against
    use-case names, descriptions, and keywords.

    Args:
        query: Natural language description of what the user wants (e.g. 'daily revenue by product').
    """
    tokens = set(query.lower().split())
    scored: list[tuple[int, dict]] = []

    for uc in _load_use_cases():
        haystack = " ".join(
            [
                uc.get("name", ""),
                uc.get("description", ""),
                " ".join(uc.get("keywords", [])),
            ]
        ).lower()
        score = sum(1 for t in tokens if t in haystack)
        if score:
            scored.append((score, uc))

    if not scored:
        return "No relevant use cases found."

    scored.sort(key=lambda x: x[0], reverse=True)
    results = [
        {
            "id": uc.get("id"),
            "name": uc.get("name"),
            "description": uc.get("description"),
            "keywords": uc.get("keywords", []),
            "relevance_score": score,
        }
        for score, uc in scored
    ]
    return json.dumps(results, indent=2)


@mcp.tool()
def list_tables() -> str:
    """List all table IDs registered in accessible_tables.yaml."""
    tables = _load_accessible_tables()
    if not tables:
        return "No tables registered. Add fully-qualified table IDs to accessible_tables.yaml."
    return json.dumps(tables, indent=2)


@mcp.tool()
def get_table_schema(table_id: str) -> str:
    """Return the locally cached schema for a registered BigQuery table.
    Run sync_table_schemas first if no local file exists yet.

    Args:
        table_id: Fully-qualified BigQuery table ID (project.dataset.table).
    """
    registered = _load_accessible_tables()
    if table_id not in registered:
        return (
            f"Table '{table_id}' is not in accessible_tables.yaml. "
            f"Registered tables: {registered}"
        )

    schema_file = TABLE_SCHEMAS_DIR / f"{table_id}.yaml"
    if not schema_file.exists():
        return (
            f"No local schema found for '{table_id}'. "
            "Run sync_table_schemas to fetch and cache the schema."
        )

    with open(schema_file, encoding="utf-8") as fh:
        return fh.read()


@mcp.tool()
def sync_table_schemas() -> str:
    """Sync table registry and local schema cache.

    1. Scans all use cases for their 'tables' field and adds any table IDs not
       already in accessible_tables.yaml (updates the file in place).
    2. Fetches the latest schema from BigQuery for every registered table and
       writes/overwrites the corresponding file in table_schemas/.
    """
    from datetime import timezone

    # --- Step 1: discover new tables from use cases ---
    registered = _load_accessible_tables()
    registered_set = set(registered)
    newly_added: list[str] = []

    for uc in _load_use_cases():
        for table_id in uc.get("tables", []):
            if table_id and table_id not in registered_set:
                registered.append(table_id)
                registered_set.add(table_id)
                newly_added.append(table_id)

    if newly_added:
        with open(ACCESSIBLE_TABLES_FILE, "w", encoding="utf-8") as fh:
            yaml.dump({"tables": registered}, fh, allow_unicode=True, sort_keys=False)

    if not registered:
        return "No tables found in accessible_tables.yaml or use case 'tables' fields."

    # --- Step 2: fetch and cache schemas ---
    TABLE_SCHEMAS_DIR.mkdir(exist_ok=True)
    client = get_bq_client()
    synced, failed = [], []

    for table_id in registered:
        try:
            table_ref = client.get_table(table_id)
            columns = [
                {
                    "name": field.name,
                    "type": field.field_type,
                    "mode": field.mode,
                    "description": field.description or "",
                }
                for field in table_ref.schema
            ]
            payload = {
                "table_id": table_id,
                "num_rows": table_ref.num_rows,
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "columns": columns,
            }
            schema_file = TABLE_SCHEMAS_DIR / f"{table_id}.yaml"
            with open(schema_file, "w", encoding="utf-8") as fh:
                yaml.dump(payload, fh, allow_unicode=True, sort_keys=False)
            synced.append(table_id)
        except Exception as exc:
            failed.append({"table_id": table_id, "error": str(exc)})

    return json.dumps(
        {"newly_registered": newly_added, "synced": synced, "failed": failed},
        indent=2,
    )


@mcp.tool()
def execute_query(sql: str, max_results: int = 1000) -> str:
    """Execute a BigQuery SQL query and return the results as JSON.

    Args:
        sql: The BigQuery SQL query to run.
        max_results: Maximum number of rows to return (default 1000).
    """
    client = get_bq_client()
    query_job = client.query(sql)
    rows_iter = query_job.result(max_results=max_results)

    columns = [field.name for field in rows_iter.schema]
    rows = [
        {col: val for col, val in zip(columns, row.values())}
        for row in rows_iter
    ]

    return json.dumps(
        {"columns": columns, "rows": rows, "total_rows": len(rows)},
        indent=2,
        default=str,
    )


@mcp.tool()
def generate_csv_from_query(sql: str, max_results: int = 50000) -> str:
    """Execute a BigQuery SQL query and save the results to a CSV file.
    Returns the path to the CSV file and basic stats.

    Args:
        sql: The BigQuery SQL query to run.
        max_results: Maximum number of rows to fetch (default 50000).
    """
    client = get_bq_client()
    query_job = client.query(sql)
    rows_iter = query_job.result(max_results=max_results)

    columns = [field.name for field in rows_iter.schema]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    row_count = 0
    for row in rows_iter:
        writer.writerow(
            {col: ("" if val is None else str(val)) for col, val in zip(columns, row.values())}
        )
        row_count += 1

    output_dir = Path(__file__).parent / "output"
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"query_result_{timestamp}.csv"
    csv_path.write_text(buf.getvalue(), encoding="utf-8")

    return json.dumps(
        {
            "csv_path": str(csv_path),
            "columns": columns,
            "total_rows": row_count,
        },
        indent=2,
    )


@mcp.tool()
def send_csv_via_email(
    csv_path: str,
    recipient_email: str,
    subject: str = "BigQuery Query Results",
    body: str = "Please find the query results attached.",
) -> str:
    """Send a CSV file to the given email address via SMTP.

    Requires the following environment variables:
      SMTP_HOST     (default: smtp.gmail.com)
      SMTP_PORT     (default: 587)
      SMTP_USER     — sender address
      SMTP_PASSWORD — sender password / app-password

    Args:
        csv_path: Absolute path to the CSV file (returned by generate_csv_from_query).
        recipient_email: Destination email address.
        subject: Email subject line.
        body: Plain-text email body.
    """
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_password = os.environ.get("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_password:
        return "Error: SMTP_USER and SMTP_PASSWORD environment variables must be set."

    csv_file = Path(csv_path)
    if not csv_file.exists():
        return f"Error: CSV file not found at '{csv_path}'."

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(csv_path, "rb") as fh:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(fh.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{csv_file.name}"')
    msg.attach(part)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, recipient_email, msg.as_string())

    return f"Email sent successfully to {recipient_email}."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

