# Axolotl - GitLab MCP Integration (Person 2)

This module implements the **GitLab integration layer** for Axolotl, an autonomous CI/CD pipeline fixer. It provides:

1. **MongoDB-backed credential storage** for managing multiple GitLab projects
2. **GitLab MCP Server** that exposes GitLab operations as tools via the Model Context Protocol
3. **FastAPI webhook server** that receives GitLab pipeline failure notifications
4. **Async/await architecture** for efficient handling of multiple concurrent operations

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│ GitLab (Pipeline Failure)                               │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Webhook Server (FastAPI)                                │
│ ├─ Receives pipeline failure events                     │
│ ├─ Looks up project in MongoDB                          │
│ └─ Signals Orchestrator                                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ Orchestrator (Person 1)                                 │
│ ├─ Analyzes logs via MCP                                │
│ ├─ Generates fix proposal                               │
│ └─ Executes fix via MCP tools                           │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ GitLab MCP Server (stdio transport)                      │
│ ├─ get_pipeline_logs                                    │
│ ├─ create_branch                                        │
│ ├─ update_file                                          │
│ └─ create_merge_request                                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ GitLab MCP Client (credentials from MongoDB)            │
│ └─ Authenticates and performs operations                │
└─────────────────────────────────────────────────────────┘
```

## Project Structure

```
Axolotl/
├── db/
│   ├── __init__.py
│   └── mongo_service.py          # MongoDB connection and CRUD
├── gitlab/
│   ├── __init__.py
│   ├── gitlab_mcp_client.py      # GitLab API client
│   └── mcp_server.py             # MCP server (stdio transport)
├── api/
│   ├── __init__.py
│   └── webhook_routes.py         # FastAPI webhook routes
├── seed_db.py                    # Database seeding utility
├── run_webhook_server.py         # Webhook server entry point
├── requirements.txt              # Python dependencies
├── .env.example                  # Environment variable template
└── CONTRIBUTING.md               # Team responsibilities
```

## Installation

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your MongoDB connection string
   ```

3. **Ensure MongoDB is running:**
   ```bash
   # On Linux/Mac with Homebrew:
   brew services start mongodb-community
   
   # Or run with Docker:
   docker run -d -p 27017:27017 mongo:latest
   ```

## Usage

### Phase 1: Seed the Database

Populate MongoDB with your GitLab project credentials:

```bash
python seed_db.py
```

This creates a `projects` collection in the `Axolotl` database with:
- **project_id**: GitLab project ID
- **gitlab_url**: GitLab base URL (e.g., https://gitlab.com)
- **access_token**: GitLab personal access token
- **author_name**: Name for automated commits
- **author_email**: Email for automated commits

### Phase 2: Start the MCP Server

The MCP server runs on stdio (standard input/output):

```bash
python gitlab/mcp_server.py
```

This server exposes the following tools:

#### Tool: `get_pipeline_logs`
Fetches logs for all failed jobs in a pipeline.

**Input:**
```json
{
  "project_id": "82917278",
  "pipeline_id": "12345"
}
```

**Output:**
```json
{
  "pipeline_id": "12345",
  "status": "failed",
  "failed_jobs": [
    {
      "job_id": "1",
      "job_name": "test",
      "status": "failed",
      "stage": "test",
      "trace": "Error: ModuleNotFoundError: No module named 'pandas'"
    }
  ]
}
```

#### Tool: `create_branch`
Creates a new fix branch.

**Input:**
```json
{
  "project_id": "82917278",
  "source_branch": "main",
  "new_branch_name": "axolotl/fix/12345"
}
```

#### Tool: `update_file`
Commits a file change.

**Input:**
```json
{
  "project_id": "82917278",
  "branch": "axolotl/fix/12345",
  "file_path": "requirements.txt",
  "content": "pandas==1.5.0\n",
  "commit_message": "fix: add pandas dependency"
}
```

#### Tool: `create_merge_request`
Creates a merge request.

**Input:**
```json
{
  "project_id": "82917278",
  "source_branch": "axolotl/fix/12345",
  "target_branch": "main",
  "title": "Fix: Add missing pandas dependency",
  "description": "Root Cause: Missing pandas in requirements.txt\n\nThis MR automatically fixes the dependency issue."
}
```

### Phase 3: Start the Webhook Server

In a separate terminal, start the FastAPI webhook server:

```bash
python run_webhook_server.py 8000
```

The server listens on:
- **Pipeline Webhooks**: `POST /webhooks/gitlab/pipeline`
- **Push Webhooks**: `POST /webhooks/gitlab/push`
- **Health Check**: `GET /health`

### Phase 4: Configure GitLab Webhooks

In your GitLab project settings:

1. Go to **Settings → Webhooks**
2. Add a webhook with URL: `http://<your-server>:8000/webhooks/gitlab/pipeline`
3. Select events: **Pipeline events**
4. Leave token empty for now (can be added later)

## Integration with the Orchestrator (Person 1)

The Orchestrator should:

1. **Connect to the MCP Server**: Use `stdio` transport to connect to `python gitlab/mcp_server.py`
2. **Call Tools**: Use the exposed tools to retrieve logs, create branches, update files, and create MRs
3. **Handle Events**: Listen to the webhook server to know when a pipeline fails

### Example Orchestrator Flow

```python
# 1. Connect to MCP server
mcp_client = connect_to_mcp_server("python gitlab/mcp_server.py")

# 2. Receive webhook notification
# Webhook tells us: project_id=82917278, pipeline_id=123

# 3. Get pipeline logs
logs = await mcp_client.call_tool("get_pipeline_logs", {
    "project_id": "82917278",
    "pipeline_id": "123"
})

# 4. Analyze with Gemini and generate fix

# 5. Create fix branch
branch_result = await mcp_client.call_tool("create_branch", {
    "project_id": "82917278",
    "source_branch": "main",
    "new_branch_name": "axolotl/fix/123"
})

# 6. Commit fix
update_result = await mcp_client.call_tool("update_file", {
    "project_id": "82917278",
    "branch": "axolotl/fix/123",
    "file_path": "requirements.txt",
    "content": "pandas==1.5.0\n",
    "commit_message": "fix: add pandas"
})

# 7. Create MR
mr_result = await mcp_client.call_tool("create_merge_request", {
    "project_id": "82917278",
    "source_branch": "axolotl/fix/123",
    "target_branch": "main",
    "title": "Fix: Add pandas",
    "description": "Automatic fix for missing dependency"
})
```

## MongoDB Schema

### Projects Collection

```json
{
  "_id": ObjectId("..."),
  "project_id": "82917278",
  "project_name": "axolotl-test",
  "gitlab_url": "https://gitlab.com",
  "access_token": "glpat-...",
  "author_name": "Axolotl Agent",
  "author_email": "agent@axolotl.local",
  "created_at": ISODate("2026-06-06T10:00:00Z"),
  "updated_at": ISODate("2026-06-06T10:00:00Z")
}
```

## Configuration

### Environment Variables

Create a `.env` file based on `.env.example`:

```bash
# MongoDB Configuration
MONGODB_CONNECTION_STRING=mongodb://localhost:27017
MONGODB_DB_NAME=Axolotl

# Server Configuration
WEBHOOK_SERVER_HOST=0.0.0.0
WEBHOOK_SERVER_PORT=8000
MCP_SERVER_PORT=5555
```

## Development & Testing

### Test MCP Server Manually

```bash
# Terminal 1: Start MCP server
python gitlab/mcp_server.py

# Terminal 2: Test with mcp-inspector (if installed)
mcp-inspector
```

### Test Webhook

```bash
curl -X POST http://localhost:8000/webhooks/gitlab/pipeline \
  -H "Content-Type: application/json" \
  -d '{
    "object_kind": "pipeline",
    "id": 12345,
    "status": "failed",
    "project_id": 82917278,
    "ref": "main",
    "sha": "abc123"
  }'
```

### Query MongoDB

```bash
# List all projects
db.projects.find()

# Find a specific project
db.projects.findOne({ "project_id": "82917278" })
```

## Error Handling

### Common Issues

1. **Connection Refused**: Ensure MongoDB is running on `localhost:27017`
2. **Project Not Found**: Run `python seed_db.py` to add projects
3. **Authentication Failed**: Verify the GitLab access token has necessary scopes
4. **Branch Already Exists**: The MCP client will handle gracefully with error message

## Security Considerations

1. **Access Tokens**: Store in environment variables, never commit to repo
2. **Webhook Tokens**: Use GitLab's webhook token feature for verification
3. **MongoDB**: Run with authentication in production
4. **HTTPS**: Use HTTPS for webhook endpoints in production

## Next Steps

1. **Person 1 (Orchestrator)**: Implement the Orchestrator to call these MCP tools
2. **Person 4 (Observability)**: Add Arize integration for tracing
3. **Person 3 (Frontend)**: Build dashboard that displays fix progress
4. **Team**: Implement end-to-end testing

## Support & Questions

For issues or questions:
- Check the main [CONTRIBUTING.md](CONTRIBUTING.md) for team structure
- Review error logs in console output
- Test individual components in isolation first
