# TEAM_DISTRIBUTION.md

# Axolotl - Team Responsibilities

## Project Overview

Axolotl is an autonomous software engineering agent that monitors GitLab CI/CD pipelines. When a pipeline fails, the agent automatically:

1. Detects the failure
2. Fetches pipeline logs
3. Analyzes the root cause using Gemini
4. Generates a targeted fix
5. Creates a new branch
6. Commits the fix
7. Raises a Merge Request
8. Waits for human approval

The system follows a Human-in-the-Loop workflow where the developer always has final approval before deployment.

---

# Team Structure

The project is divided into independent modules to minimize merge conflicts and allow parallel development.

## Person 1 - Agent & Orchestration Lead

### Owner

Core AI Agent Logic

### Responsibilities

* Gemini Integration
* Prompt Engineering
* Root Cause Analysis
* Fix Generation
* Agent Workflow Design
* Orchestration Logic

### Files Owned

```text
agents/
├── base_agent.py
├── ci_fix_agent.py
└── prompt_builder.py

orchestrator/
├── pipeline_orchestrator.py
└── event_types.py

schemas/
├── pipeline.py
├── fix.py
└── events.py
```

### Expected Deliverables

#### Base Agent

```python
class BaseAgent:
    async def analyze(self):
        pass
```

#### CI Fix Agent

```python
fix = await agent.analyze(logs)
```

Input:

```text
Pipeline Logs
```

Output:

```json
{
  "root_cause": "Missing dependency",
  "file_path": "requirements.txt",
  "updated_content": "...",
  "commit_message": "fix: add pandas"
}
```

### Success Criteria

* Agent identifies supported failure types
* Agent generates valid fixes
* Returns standardized FixProposal object

---

## Person 2 - GitLab MCP Lead

### Owner

GitLab Integration Layer

### Responsibilities

* GitLab MCP Integration
* Webhook Processing
* Pipeline Log Retrieval
* Branch Creation
* File Updates
* Commit Creation
* Merge Request Creation

### Files Owned

```text
gitlab/
├── gitlab_mcp_client.py
├── repository_service.py
├── pipeline_service.py
└── mr_service.py

api/
└── webhook_routes.py
```

### Expected Deliverables

#### Get Pipeline Logs

```python
await gitlab.get_pipeline_logs(
    project_id,
    pipeline_id
)
```

#### Create Branch

```python
await gitlab.create_branch(
    source_branch,
    new_branch
)
```

#### Commit Fix

```python
await gitlab.commit_fix(
    branch_name,
    fix
)
```

#### Create Merge Request

```python
await gitlab.create_merge_request(
    source_branch,
    target_branch
)
```

### Success Criteria

* Can fetch failed pipeline logs
* Can create branch
* Can commit file changes
* Can raise merge requests

---

## Person 3 - Frontend & Dashboard Lead

### Owner

Developer Dashboard

### Responsibilities

* React Frontend
* Terminal UI
* WebSocket Client
* Agent Activity Feed
* Status Panels
* Merge Request Display

### Files Owned

```text
frontend/
```

### Expected Deliverables

#### Terminal Dashboard

```text
[21:05:22] Pipeline Failed

[21:05:23] Agent Activated

[21:05:24] Fetching Logs

[21:05:30] Root Cause Detected

[21:05:35] Generating Fix

[21:05:40] Merge Request Created
```

#### Status Cards

```text
Pipelines Monitored

Failed Pipelines

Auto Fixes Created

Successful Fixes

Average Fix Time
```

### Success Criteria

* Live updates via WebSocket
* Terminal theme UI
* Easy-to-understand demo experience

---

## Person 4 - Observability & Infrastructure Lead

### Owner

Arize + Event Streaming

### Responsibilities

* Arize Integration
* Trace Collection
* Agent Observability
* WebSocket Backend
* Event Broadcasting
* Demo Metrics

### Files Owned

```text
observability/
├── arize_service.py
└── trace_models.py

websocket/
├── connection_manager.py
└── event_publisher.py
```

### Expected Deliverables

#### Trace Creation

```python
await arize.create_trace(
    input_data,
    output_data
)
```

#### Event Publishing

```python
await publisher.publish(
    "Analyzing logs..."
)
```

### Success Criteria

* Agent traces visible in Arize
* All major actions logged
* WebSocket events successfully broadcast

---

# Shared Data Models

These files are shared contracts.

No changes without team discussion.

## PipelineFailure

```python
class PipelineFailure:
    project_id: str
    pipeline_id: str
    branch: str
    logs: str
```

## FixProposal

```python
class FixProposal:
    root_cause: str
    file_path: str
    updated_content: str
    commit_message: str
```

## Event

```python
class Event:
    timestamp: str
    message: str
```

---

# Integration Flow

```text
GitLab Pipeline Failure
            │
            ▼
Webhook Received
            │
            ▼
Pipeline Orchestrator
            │
    ┌───────┼────────┐
    ▼       ▼        ▼

GitLab   Agent    Events

            │
            ▼
      Fix Proposal

            │
            ▼
Create Branch

            │
            ▼
Commit Fix

            │
            ▼
Create MR

            │
            ▼
Await Human Approval
```

---

# Event Flow

The dashboard receives events through WebSockets.

Examples:

```text
Pipeline failed

Fetching pipeline logs

Analyzing root cause

Generating fix

Creating branch

Committing changes

Creating merge request

Waiting for approval
```

These events should be:

1. Broadcast to Frontend
2. Logged to Arize

---

# Orchestrator Ownership

Only Person 1 modifies:

```text
orchestrator/pipeline_orchestrator.py
```

This file acts as the central workflow controller.

All other modules expose services and methods used by the orchestrator.

---

# Branching Strategy

## Person 1

```text
feature/agent-core
```

## Person 2

```text
feature/gitlab-mcp
```

## Person 3

```text
feature/frontend-dashboard
```

## Person 4

```text
feature/observability
```

---

# Merge Rules

* No direct pushes to main
* All changes through Pull Requests
* One reviewer minimum
* Shared schemas require team approval
* Orchestrator changes require Person 1 approval

---

# MVP Scope

The agent only needs to support:

## Case 1

```text
ModuleNotFoundError
```

Fix:

```text
Update requirements.txt
```

## Case 2

```text
Formatting Failure
```

Fix:

```text
Run formatter (Black or any popular formater research it pleaseeeeeeeee)
```

## Case 3

```text
Lint Failure
```

Fix:

```text
Apply Gemini-generated patch
```

Anything outside these categories is considered out-of-scope for the hackathon MVP.

---

# Demo Flow

1. Push intentionally broken code
2. GitLab Pipeline fails
3. Webhook triggers agent
4. Dashboard shows live activity
5. Agent analyzes logs
6. Agent generates fix
7. Agent creates Merge Request
8. Show Arize trace
9. Approve Merge Request
10. Pipeline passes
11. Deployment succeeds

Goal:

"A self-healing CI/CD pipeline with human approval and full observability."
