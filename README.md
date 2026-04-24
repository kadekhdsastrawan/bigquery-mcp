# bigquery-mcp

# About The Project
This repository contains the MCP Server that can be utilized to store the use cases query as well as the function to communicate with the BigQuery. The aim for the use cases is to give context / understanding to the LLM about the use cases / knowledge base that the repository has.

# Workflow
THe workflow of the MCP will be like this:
- Users create prompt
- LLM parse the prompt and search relevant use cases to cover the needs
- LLM construct query based on the use case template
- LLM generate csv
- LLM send the CSV to users email

# How to Use MCP
1. Authenticate your credentials with default authentication.
```shell
gcloud auth authentication default
```
2. Create `use_cases/` folder in the root directory.
3. Add the configuration file under copilot configuration (`~/.copilot/config.json`)
```json
// COPILOT CONFIGURATION
  "mcpServers": {
    "bigquery-mcp-use-case": {
      "command": "PYTHON_PATH",
      "args": [
        "PYTHON_MCP_FILE_PATH.py"
      ],
      "env": {
        "GCP_PROJECT_ID": "YOUR_GCP_PROJECT_ID"
      }
    }
  }
// END OF CONFIGURATION
```
4. After you configure the MCP, then try to test with `copilot` in Terminal
```shell
copilot
```
5. Check the mcp with this command:
```shell
/mcp
```

