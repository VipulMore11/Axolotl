<div align="center">

# 🦎 Axolotl

### *Self-Healing CI/CD Pipelines — Powered by AI*

**Axolotl** is an autonomous software engineering agent that watches your GitLab CI/CD pipelines.  
The moment a pipeline fails, Axolotl springs into action: it fetches logs, analyzes the root cause with Gemini AI, writes the fix, opens a Merge Request, and waits for your approval — all in under a minute.
### 🚀 Live Demo - https://axolotl-hvh1.onrender.com/

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-16-black?style=flat-square&logo=next.js)](https://nextjs.org)
[![Python](https://img.shields.io/badge/Python-3.12-blue?style=flat-square&logo=python)](https://python.org)
[![MongoDB](https://img.shields.io/badge/MongoDB-Atlas-47A248?style=flat-square&logo=mongodb)](https://mongodb.com)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-4285F4?style=flat-square&logo=google)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](LICENSE)

</div>

---

## ✨ Key Features

- 🔍 **Automatic Failure Detection** — Listens to GitLab pipeline webhooks in real time; no manual polling required.
- 🤖 **AI Root-Cause Analysis** — Uses Google Gemini 2.5 Flash to diagnose failures: missing dependencies, lint errors, formatting issues, and more.
- 🔧 **Autonomous Fix Generation** — Produces a targeted code patch and commits it directly to a dedicated `axolotl/fix/<pipeline-id>` branch.
- 📋 **Auto Merge Request** — Opens a fully-described MR with root cause, changed file, and pipeline reference — ready for one-click review.
- 👤 **Human-in-the-Loop Gate** — Every fix is gated behind a developer's explicit *Approve & Merge* or *Reject* decision. The AI never deploys unsupervised.
- ⚡ **Real-Time WebSocket Dashboard** — Watch every step of the agent workflow live, with a terminal-style log feed streamed via WebSockets.
- 🔌 **MCP-Powered GitLab Integration** — All Git operations (branch create, file commit, MR creation) run through the GitLab MCP Server — a clean, auditable tool interface.
- 🛡️ **Circuit-Breaker Guards** — Prevents infinite fix loops: deduplication by pipeline ID, per-project cooldown timers, and skips failures on its own fix branches.
- 📊 **Observability** — Every agent action is persisted to MongoDB and broadcast over WebSocket; pluggable Arize tracing support included.
- ⚙️ **Project Settings Dashboard** — Connect/disconnect GitLab repos, toggle auto-fix per project, and tune agent confidence thresholds — all from the UI.

---

## 🚀 How the Pipeline Fix System Works

The fix system follows a strict, auditable 8-stage workflow from failure detection to human-approved deployment.

### High-Level Flow

```mermaid
flowchart TD
    A([🔴 GitLab Pipeline Fails]) --> B[POST /webhooks/gitlab/pipeline]
    B --> C{Circuit Breaker\nGuards}
    C -- Ignored --> D([⏭ Skip: duplicate / cooldown\n/ axolotl branch])
    C -- Proceed --> E[Background Task: process_pipeline_failure]

    E --> F[🔌 Connect to GitLab MCP Server\nvia stdio transport]

    F --> G[📥 MCP: get_pipeline_logs\nFetch failed job traces]
    G --> H{Logs\nFound?}
    H -- No --> Z1([❌ Fix Failed: no logs])
    H -- Yes --> I[LangGraph 8-stage CI fix\nworkspace → review]
    I --> J[FixProposal\nroot_cause · file_path\nupdated_content · commit_message]

    J --> K[🌿 MCP: create_branch\naxolotl/fix/<pipeline_id>]
    K --> L{Branch\nCreated?}
    L -- No --> Z2([❌ Fix Failed: branch error])
    L -- Yes --> M[💾 MCP: update_file\nCommit the fix]

    M --> N{Commit\nSuccess?}
    N -- No --> Z3([❌ Fix Failed: commit error])
    N -- Yes --> O[📬 MCP: create_merge_request\nAuto-generated description]

    O --> P{MR\nCreated?}
    P -- No --> Z4([❌ Fix Failed: MR error])
    P -- Yes --> Q([⏳ Awaiting Human Approval])

    Q --> R{Developer\nDecision}
    R -- ✅ Approve & Merge --> S([🟢 Fix Deployed\nPipeline Passes])
    R -- ❌ Reject --> T([🔁 MR Closed\nManual Review])

    style A fill:#dc2626,color:#fff
    style S fill:#16a34a,color:#fff
    style Q fill:#d97706,color:#fff
    style D fill:#6b7280,color:#fff
    style Z1 fill:#991b1b,color:#fff
    style Z2 fill:#991b1b,color:#fff
    style Z3 fill:#991b1b,color:#fff
    style Z4 fill:#991b1b,color:#fff
```

### Stage-by-Stage Sequence

```mermaid
sequenceDiagram
    participant GL as GitLab
    participant WH as Webhook Handler
    participant ORCH as Orchestrator
    participant MCP as MCP Server
    participant AI as Gemini AI
    participant DB as MongoDB
    participant WS as WebSocket
    participant DEV as Developer

    GL->>WH: POST /webhooks/gitlab/pipeline (pipeline failed)
    WH->>WH: Circuit-breaker checks (dedup, cooldown, branch guard)
    WH->>ORCH: background_task: handle_pipeline_failure()
    ORCH->>WS: Event: pipeline_failed
    ORCH->>DB: Persist event

    ORCH->>MCP: get_pipeline_logs(project_id, pipeline_id)
    MCP->>GL: GitLab API — fetch job traces
    GL-->>MCP: Failed job logs
    MCP-->>ORCH: failed_jobs[...]
    ORCH->>WS: Event: fetching_logs

    ORCH->>AI: CIFixAgent.analyze(combined_logs)
    AI-->>ORCH: FixProposal { root_cause, file_path, updated_content, commit_message }
    ORCH->>WS: Event: analyzing, generating_fix
    ORCH->>DB: Persist AgentTrace

    ORCH->>MCP: create_branch(axolotl/fix/id, from: main)
    MCP->>GL: GitLab API — create branch
    ORCH->>WS: Event: creating_branch

    ORCH->>MCP: update_file(branch, file_path, content, commit_message)
    MCP->>GL: GitLab API — commit file
    ORCH->>WS: Event: committing

    ORCH->>MCP: create_merge_request(source=axolotl/fix/id, target=main)
    MCP->>GL: GitLab API — open MR
    ORCH->>WS: Event: creating_mr, waiting_approval
    ORCH->>DB: Persist all events

    GL-->>DEV: MR notification
    DEV->>WH: POST /api/merge-requests/{project}/{iid}/merge OR /reject
    WH->>GL: GitLab API — merge or close MR
```

### Event → UI Stage Mapping

| Backend Event | Dashboard Stage | Log Level |
|---|---|---|
| `pipeline_failed` | Detect Failure | `error` |
| `fetching_logs` | Fetch Pipeline Logs | `info` |
| `analyzing` | Analyze Root Cause | `info` |
| `generating_fix` | Generate Fix | `info` |
| `creating_branch` | Create Branch | `info` |
| `committing` | Commit Fix | `success` |
| `creating_mr` | Raise Merge Request | `success` |
| `waiting_approval` | Human Approval | `warn` |
| `fix_succeeded` | — (terminal) | `success` |
| `fix_failed` | — (terminal) | `error` |

---

## 🖼️ UI Screenshots

**Overview Dashboard — Live Agent Workflow**

<div align="center">
<img src="Screenshots/dashboard_overview.png" alt="Axolotl Dashboard — Live Agent Workflow" >
</div>

---

**Pipeline Monitor — Status at a Glance**

<div align="center">
<img src="Screenshots/pipelines_view.png" alt="Axolotl Pipeline Monitor" >
</div>

---

**Merge Request Panel — Human-in-the-Loop Gate**

<div align="center">
<img src="Screenshots/merge_request_panel.png" alt="Axolotl Merge Request Approval Panel" >
</div>

---

**Settings — Project & Agent Configuration**

<div align="center">
<img src="Screenshots/settings_page.png" alt="Axolotl Settings Page" >
</div>

---

## 🏗️ Tech Stack & Dependencies

### Backend

| Layer | Technology |
|---|---|
| Framework | [FastAPI](https://fastapi.tiangolo.com) 0.115 + Uvicorn |
| AI / LLM | [Google Gemini 2.5 Flash](https://ai.google.dev) via LangChain (`langchain-google-genai`) |
| Agent Framework | [LangGraph](https://langchain-ai.github.io/langgraph/) eight-stage Evaluator-Optimizer loop with artifact contracts (Flash for analysis/tasks; Pro for architect/dev/review) |
| Agent Observability | [LangSmith](https://smith.langchain.com) tracing (set `LANGSMITH_TRACING=true`) |
| Fix Validation | Local Docker sandbox (`axolotl-validator`) — allowlisted pip/ruff/py_compile checks |
| MCP Transport | [Model Context Protocol (MCP)](https://modelcontextprotocol.io) — stdio client/server |
| Database | MongoDB (Motor async driver) |
| HTTP Client | httpx (async) |
| Auth | GitLab OAuth 2.0 + JWT (python-jose) |
| Observability | Arize Phoenix (pluggable) |
| WebSockets | FastAPI WebSocket + custom connection manager |
| Runtime | Python 3.12 |

### Frontend

| Layer | Technology |
|---|---|
| Framework | [Next.js 16](https://nextjs.org) (App Router) |
| Language | TypeScript 5.7 |
| Styling | Tailwind CSS 4 |
| Components | shadcn/ui + Base UI |
| Icons | Lucide React |
| Real-time | Native WebSocket API |

### Infrastructure

| Component | Technology |
|---|---|
| Containerization | Docker |
| Tunnel (dev) | ngrok |
| CI Source | GitLab (webhook integration) |

---

## 📋 Prerequisites

Before running Axolotl, make sure you have:

- **Python 3.12+**
- **Node.js 20+** and **pnpm** (or npm)
- **MongoDB** — local or [Atlas](https://cloud.mongodb.com) cluster
- **GitLab account** with a project you own (Developer access or above)
- **Google Gemini API key** — get one at [Google AI Studio](https://aistudio.google.com)
- **Docker** (recommended) — for local patch validation via the `axolotl-validator` image
- **ngrok** (for local development, to expose your webhook endpoint publicly)
- **GitLab OAuth Application** — configured in *GitLab → Preferences → Applications*

---

## ⚙️ Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/axolotl.git
cd axolotl
```

### 2. Backend Setup

```bash
cd backend

# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Build the CI fix validator image (required when CI_FIX_VALIDATE=true)
docker build -t axolotl-validator -f sandbox/Dockerfile sandbox
```

#### Configure environment variables

Create a `.env` file inside `backend/` and fill in your values:

```dotenv
# ── Gemini AI ──────────────────────────────────────────────
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-2.5-flash
# Persona model split (artifact-contract pipeline)
GEMINI_FLASH_MODEL=gemini-2.5-flash
GEMINI_PRO_MODEL=gemini-2.5-pro

# ── CI Fix Engine (LangGraph default) ─────────────────────
CI_FIX_ENGINE=langgraph
CI_FIX_VALIDATE=true
CI_FIX_MAX_ATTEMPTS=3
# CI_FIX_VALIDATOR_IMAGE=axolotl-validator
# Set CI_FIX_VALIDATE=false on hosts without Docker (e.g. some PaaS)

# ── Search/Replace patch engine ────────────────────────────
# CI_FIX_BLOCK_RETRIES=2        # targeted retries per failed SEARCH block
# CI_FIX_FUZZY_THRESHOLD=0.85   # min Levenshtein similarity for a fuzzy match
# CI_FIX_EXPANSION_MAX_FILES=25 # max files after same-error fan-out

# ── CI log digest (LLM-facing; raw logs kept for regex tools) ─
# CI_FIX_LOG_DIGEST_CHARS=3500  # max chars sent to LLM personas
# CI_FIX_LOG_TAIL_LINES=120     # failure-biased tail window
# CI_FIX_LOG_MAX_BLOCKS=12      # max discrete error blocks in the digest

# ── LangSmith (optional tracing for LangGraph runs) ───────
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=your_langsmith_api_key_here
LANGSMITH_PROJECT=axolotl-ci-fix
# LANGSMITH_ENDPOINT=https://api.smith.langchain.com

# ── MongoDB ────────────────────────────────────────────────
MONGODB_CONNECTION_STRING=mongodb+srv://user:pass@cluster.mongodb.net/axolotl

# ── Neo4j (Knowledge Base graph) ───────────────────────────
# Paste the credentials Neo4j Aura gives you when the instance is created
NEO4J_URI=neo4j+s://xxxxxxxx.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your_neo4j_password_or_api_key
NEO4J_DATABASE=neo4j
# NEO4J_ENABLED=false   # hard-disable KB grounding + knowledge writes

# ── GitLab OAuth ────────────────────────────────────────────
GITLAB_CLIENT_ID=your_gitlab_oauth_client_id
GITLAB_CLIENT_SECRET=your_gitlab_oauth_client_secret
GITLAB_REDIRECT_URI=https://your-ngrok-url.ngrok-free.app/auth/gitlab/callback

# ── JWT ────────────────────────────────────────────────────
JWT_SECRET_KEY=your_super_secret_jwt_key_here
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=1440

# ── Frontend ────────────────────────────────────────────────
FRONTEND_URL=http://localhost:3000

# ── Webhook ─────────────────────────────────────────────────
WEBHOOK_SECRET=axolotl-webhook-secret
```

#### Start the backend server

```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 3. Frontend Setup

```bash
cd frontend

# Install dependencies
pnpm install       # or: npm install
```

Create a `.env.local` file inside `frontend/`:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_WS_URL=ws://localhost:8000
```

```bash
# Start the dev server
pnpm dev           # or: npm run dev
```

The frontend will be available at **http://localhost:3000**.

### 4. Expose Webhook (Development)

GitLab needs a public URL to send webhooks. Use ngrok:

```bash
ngrok http 8000
```

Copy the generated HTTPS URL (e.g. `https://abc123.ngrok-free.app`) and update `GITLAB_REDIRECT_URI` in `backend/.env`.

### 5. Docker (Optional)

```bash
# Build and run the backend container
docker build -t axolotl-backend .
docker run -p 8000:8000 --env-file backend/.env axolotl-backend
```

---

## 🎮 Usage Examples

### Triggering the Agent (Automatic)

Simply push a commit with a CI failure to any watched GitLab (or Bitbucket) project. Axolotl will automatically:
1. Receive the pipeline webhook and fetch logs via MCP
2. Run the LangGraph agent with artifact contracts, Knowledge Base grounding, and same-error fan-out (workspace → requirements → architecture → **error expansion** → tasks → implement → validate → review). CI logs are treated as a seed; the agent searches the repo for sibling files sharing the failure signature so fail-fast pipelines still get a multi-file fix. The Developer emits SEARCH/REPLACE blocks against real repo file contents. Analyst/Tech Lead use Gemini Flash; Architect/Developer/Evaluator use Gemini Pro.
3. Apply Git Operations via MCP (branch, **each** file update, merge request)
4. Wait for human approval on the MR — on approve/merge, successful fixes are written asynchronously into the Knowledge Base for future grounding

### Personal-repo demo (no company admin access)

If you cannot register webhooks on a company repo, use a **personal** GitLab/Bitbucket project:

1. Create a small Python repo with an intentional failure (e.g. missing dependency in `requirements.txt`).
2. Build the validator: `docker build -t axolotl-validator -f backend/sandbox/Dockerfile backend/sandbox`
3. Run Axolotl locally, expose with ngrok, connect the personal project in Settings.
4. Push the failing commit (or `curl` a Bitbucket `repo:commit_status_updated` payload to `/webhooks/bitbucket/pipeline`).
5. Watch the dashboard: analyze → validate → MR → approve.

Set `CI_FIX_ENGINE=legacy` only if you need the old one-shot Gemini path. Set `CI_FIX_VALIDATE=false` on hosts without Docker.

### LangSmith traces

With `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` set, every LangGraph CI-fix run appears in [smith.langchain.com](https://smith.langchain.com) under project `LANGSMITH_PROJECT` (default `axolotl-ci-fix`). You should see:

- Parent run: `ci_fix_analyze` / `ci-fix-<pipeline_id>`
- Graph nodes: `workspace_setup` → `requirements_analysis` → `technical_architecture` → `error_expansion` → `task_breakdown` → `code_implementation` → `testing_validation` → `code_review`
- Artifacts in state: `ArchitecturePlan`, `error_signature`, `expanded_files[]`, `task_breakdown[]`, `validation_failures[]`, `review_history[]` (`CritiqueResult`)
- Child tool span: `docker_validate_patch`
- Revise loops back to `code_implementation` with **targeted** edits when validation or review fails (up to `CI_FIX_MAX_ATTEMPTS`)
- Metadata includes `flash_model` / `pro_model`

Startup logs will print `[LangSmith] Tracing enabled → project=...` when configured correctly.

### CI log digest (custom reducer)

Full job traces stay in `state.logs` for regex tooling (`line_hints`, `error_signature`, fan-out). Before any LLM call, `workspace_setup` runs a **deterministic** reducer (`agents/log_reducer.py`) that:

1. Strips ANSI and drops pip/Docker/download noise  
2. Extracts every traceback, pytest failure, lint finding, and error/summary line  
3. Always keeps a failure-biased tail window (useful part of CI is usually at the end)  
4. Packs the result into `logs_digest` / `relevant_errors` (default ~3.5k chars)

Analyst, Architect, and Developer prompts use **only** the digest — so LangSmith traces no longer dump multi‑MB build diaries into the model. No Headroom/LLM summarizer: rules only, stable and testable.

### Search/Replace patch engine (code surgery)

Stage 5 no longer regenerates whole files. The Developer Agent (Gemini Pro) fetches the **real file contents** from the repo (via the `get_file_contents` MCP tool) and emits Aider-style `SEARCH/REPLACE` blocks in a **single pass** — no extra formatting LLM call. The backend engine in `agents/patch_utils.py` then applies them:

- **Middle-out search** — Stage 2 extracts `file:line` hints from the stack trace for free (regex, no LLM). The engine scans outward from that line using Levenshtein fuzzy matching, so the right spot is found first even in 2k+ line files, and duplicated code resolves to the occurrence nearest the failure.
- **Relative indentation preservation** — the search block and the matched file lines describe the same code in two styles, giving a per-level whitespace mapping. Replace lines are rewritten through it, so an LLM that hallucinates 2-space indents into a tabs file cannot corrupt formatting.
- **Rich diagnostic partial retries** — when a block fails to match, `difflib` finds the closest real lines and the agent asks the LLM to fix **only that block** ("N of M blocks applied successfully. Do not resend them."), keeping applied blocks cached. Unresolved failures surface to the Evaluator and the revision loop.

Empty `search_block` creates a new file. Downstream stages are unchanged: applied blocks become full-content `file_patches` for Docker validation, code review, and the per-file MCP commits.

### Same-error fan-out (`error_expansion`)

CI webhooks / job logs are often **fail-fast**: only the first broken file appears in the trace even when the same bug exists in other files. After the Architect drafts a plan, `error_expansion`:

1. Builds an `error_signature` from the logs (module name, failing source line, lint codes, import snippets).
2. Calls MCP `search_code` to scan the repository for those literal patterns.
3. Merges hits into `expanded_files` / `architecture_plan.affected_files` (capped by `CI_FIX_EXPANSION_MAX_FILES`).
4. Stage 5 is instructed to patch **every** expanded sibling, not just the seed file.
5. Stage 6 re-checks that actionable signature patterns no longer remain in expanded files; leftovers force another implementation loop.

Pure dependency fixes still prioritize `requirements.txt`, and legitimate `import <missing_module>` usages are not treated as leftover failures.

### Knowledge Base (Neo4j)

The Knowledge Base is a provenance graph in Neo4j that lets the agent reason across pipeline sessions. Nodes carry the shared `:KBNode` label plus a type label — `Entity` (touched files/dependencies), `Claim` (a diagnosed root cause), `Source` (pipeline logs), `Artifact` (the approved multi-file patch set), and `Run` (an agent execution). Relationships are `MENTIONS`, `SUPPORTS`, `CONTRADICTS`, `DERIVED_FROM`, and `SUPERSEDES`.

The graph is used at two points:

- **Read (grounding)** — during `requirements_analysis`, the current error signature is matched against `Claim` nodes through the `kb_claim_fulltext` index, and the newest non-superseded `Artifact` for each hit is injected into the analyst's context.
- **Write (post-HITL)** — approving or merging an MR schedules an asynchronous write of `Run → Claim → Artifact → Entity` with full provenance. Earlier artifacts for the same claim get a `SUPERSEDES` edge, so history is preserved rather than overwritten.

Schema (uniqueness constraint plus the full-text index) is provisioned automatically on startup. If `NEO4J_URI`/`NEO4J_PASSWORD` are unset or the instance is unreachable, the KB silently disables itself and the pipeline runs without grounding.

Verify the connection with a write/read round-trip that cleans up after itself:

```bash
cd backend
python -m scripts.verify_kb
```

Inspect what the agent has learned in Neo4j Browser:

```cypher
// Claims and the fix currently backing them
MATCH (c:Claim)-[:SUPPORTS]->(a:Artifact)
WHERE NOT EXISTS { (:Artifact)-[:SUPERSEDES]->(a) }
RETURN c.label AS root_cause, a.commit_message AS fix, a.pipeline_id AS pipeline;

// Full provenance for one project
MATCH (n:KBNode {project_id: '<project_id>'})-[r]->(m:KBNode)
RETURN n, r, m;
```

### Watching the Live Dashboard

Open `http://localhost:3000`. The dashboard connects over WebSocket and displays real-time events as the agent works through each stage.

### Approving a Fix via API

```bash
# Approve and merge a fix MR
curl -X POST http://localhost:8000/api/merge-requests/{project_id}/{mr_iid}/merge \
  -H "Authorization: Bearer <your_jwt_token>"

# Reject a fix MR
curl -X POST http://localhost:8000/api/merge-requests/{project_id}/{mr_iid}/reject \
  -H "Authorization: Bearer <your_jwt_token>"
```

### Connecting a GitLab Project via API

```bash
curl -X POST http://localhost:8000/api/settings/projects \
  -H "Authorization: Bearer <your_jwt_token>" \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "12345678",
    "gitlab_url": "https://gitlab.com",
    "auto_fix": true
  }'
```

### Fetching Agent Activity Events

```bash
curl http://localhost:8000/api/activity/events \
  -H "Authorization: Bearer <your_jwt_token>"
```

---

## 📚 API Documentation

Interactive Swagger docs are available at **`http://localhost:8000/docs`** when the server is running.

> All endpoints except `/health`, `/`, and `/auth/*` require a `Bearer <JWT>` token in the `Authorization` header.

---

### 🔐 Authentication

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/auth/gitlab/login` | Redirect to GitLab OAuth authorization page |
| `GET` | `/auth/gitlab/callback?code=<code>` | Handle OAuth callback — exchange code for JWT, redirect to frontend |
| `POST` | `/auth/logout` | Client-side logout (instructs client to discard JWT) |
| `GET` | `/auth/me` | Return the currently authenticated user profile |

**Example — Get current user:**
```bash
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer eyJ..."
```
```json
{
  "id": "6840ab12cd34ef567890abcd",
  "username": "johndoe",
  "name": "John Doe",
  "avatar_url": "https://gitlab.com/uploads/user/avatar/..."
}
```

---

### 🔔 Webhooks

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/webhooks/gitlab/pipeline` | Receive GitLab pipeline events; triggers agent on failure |
| `POST` | `/webhooks/gitlab/push` | Receive GitLab push events (logging only) |
| `POST` | `/webhooks/gitlab/test` | Debug endpoint — echoes the received payload |

**Webhook Payload (GitLab pipeline event):**
```json
{
  "object_kind": "pipeline",
  "object_attributes": {
    "id": 98765,
    "status": "failed",
    "ref": "main",
    "sha": "abc123def456"
  },
  "project": {
    "id": 12345678
  }
}
```

**Response:**
```json
{
  "status": "received",
  "project_id": "12345678",
  "pipeline_id": "98765",
  "message": "Pipeline failure received, agent will analyze and create fix"
}
```

---

### 📊 Dashboard

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/dashboard/summary` | Aggregated stats: project count, agent metrics |
| `GET` | `/api/dashboard/active-session` | Most recent active pipeline fix session with its events |

**Example — Dashboard Summary:**
```json
{
  "projects_count": 3,
  "metrics": {
    "total_failures": 12,
    "fixes_created": 10,
    "fixes_succeeded": 8,
    "success_rate": 80.0,
    "avg_fix_time_seconds": 47
  }
}
```

---

### 🔧 Pipelines

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/pipelines?per_page=20&page=1` | List pipelines from all watched projects, enriched with agent status |
| `GET` | `/api/pipelines/{pipeline_id}?project_id=<id>` | Get pipeline detail and its job list |

**Pipeline Status Values:**

| Value | Meaning |
|---|---|
| `running` | Pipeline is currently executing |
| `passed` | Pipeline succeeded |
| `failed` | Pipeline failed (agent not engaged) |
| `fixing` | Pipeline failed and agent is actively generating a fix |

---

### 📬 Merge Requests

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/merge-requests?state=all&per_page=20&page=1` | List all MRs from watched projects |
| `GET` | `/api/merge-requests/{project_id}/{mr_iid}` | Get MR detail including file diff |
| `POST` | `/api/merge-requests/{project_id}/{mr_iid}/approve` | Approve an MR via GitLab API |
| `POST` | `/api/merge-requests/{project_id}/{mr_iid}/merge` | Merge an approved MR |
| `POST` | `/api/merge-requests/{project_id}/{mr_iid}/reject` | Close/reject an MR |

**Example — List MRs response:**
```json
{
  "merge_requests": [
    {
      "iid": "!42",
      "raw_iid": 42,
      "title": "🦎 Axolotl Fix: fix: add missing pandas dependency",
      "project": "myorg/my-api",
      "project_id": "12345678",
      "source_branch": "axolotl/fix/98765",
      "target_branch": "main",
      "author": "Axolotl Agent",
      "author_is_agent": true,
      "status": "open",
      "additions": 3,
      "deletions": 0,
      "files_changed": 1,
      "pipeline_passing": true,
      "root_cause": "Missing pandas dependency in requirements.txt",
      "web_url": "https://gitlab.com/myorg/my-api/-/merge_requests/42"
    }
  ],
  "total": 1
}
```

---

### ⚙️ Settings

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/settings/gitlab-repos?search=&per_page=20` | Browse GitLab repos the user has access to |
| `GET` | `/api/settings/projects` | List all connected (watched) projects |
| `POST` | `/api/settings/projects` | Connect a new GitLab project (auto-registers webhook) |
| `PUT` | `/api/settings/projects/{project_id}` | Update project settings (e.g. toggle auto-fix) |
| `DELETE` | `/api/settings/projects/{project_id}` | Disconnect a project and unregister its webhook |
| `GET` | `/api/settings/agent` | Get agent configuration for the current user |
| `PUT` | `/api/settings/agent` | Update agent configuration |

**Add Project Request Body:**
```json
{
  "project_id": "12345678",
  "gitlab_url": "https://gitlab.com",
  "auto_fix": true
}
```

**Agent Settings Request Body:**
```json
{
  "confidence_threshold": 75,
  "require_approval": true,
  "auto_branch": true,
  "notify_failures": true
}
```

---

### 📈 Activity

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/activity/events?limit=50&event_type=<type>` | List agent activity events, newest first |
| `GET` | `/api/activity/metrics` | Aggregate lifetime agent metrics |

**Event Type Filter Values:**
`detection` · `analysis` · `fix` · `merge-request` · `approval` · `merged` · `rejected`

---

### 📡 WebSocket

| Endpoint | Description |
|---|---|
| `WS /ws/{session_id}` | Connect to a real-time event stream. Use `session_id=dashboard` to receive all events across all pipeline sessions. |

**Incoming message format:**
```json
{
  "event_type": "analyzing",
  "message": "Analyzing root cause with AI agent...",
  "timestamp": "2026-06-13T02:30:00Z",
  "session_id": "pipeline-98765"
}
```

---

### 🩺 System

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check — returns `{"status": "healthy", "service": "axolotl"}` |
| `GET` | `/` | Root — returns service name and version |

---

## 🗂️ Project Structure

```
axolotl/
├── Dockerfile                        # Backend container definition
├── .gitignore
│
├── backend/
│   ├── main.py                       # FastAPI app entrypoint, router registration, lifespan
│   ├── requirements.txt              # Python dependencies
│   ├── .env                          # Environment variables (gitignored)
│   │
│   ├── agents/                       # AI Agent layer
│   │   ├── base_agent.py             # Abstract BaseAgent interface
│   │   ├── ci_fix_agent.py           # Facade: LangGraph (default) or legacy Gemini
│   │   ├── langgraph_ci_fix_agent.py # 8-stage artifact contracts (Flash/Pro, multi-file, KB grounding)
│   │   ├── knowledge_schema.py       # KB node/edge types
│   │   ├── knowledge_store.py        # Neo4j KB graph store (Cypher)
│   │   ├── knowledge_extraction.py   # Post-HITL KB write
│   │   ├── patch_utils.py            # Search/Replace engine: middle-out fuzzy match, reindent, diagnostics
│   │   ├── error_signature.py        # CI seed → searchable signature + fan-out merge helpers
│   │   ├── log_reducer.py            # Deterministic CI log digest for LLM prompts
│   │   ├── langsmith_tracing.py      # LangSmith env + run config helpers
│   │   ├── sandbox_tools.py          # Ephemeral Docker validation helpers
│   │   ├── ci_fix_state.py           # CIFixState + FilePatch/ArchitecturePlan/CritiqueResult
│   │   └── prompt_builder.py         # Prompt engineering for CI logs
│   ├── sandbox/                      # axolotl-validator Docker image
│   │   ├── Dockerfile
│   │   └── axolotl_validate.py
│   │
│   ├── orchestrator/                 # Workflow coordination
│   │   ├── pipeline_orchestrator.py  # Core: full fix lifecycle (MCP + agent)
│   │   └── event_types.py            # EventType enum
│   │
│   ├── gitlab_client/                # GitLab MCP Server
│   │   ├── mcp_server.py             # MCP tool definitions (get_logs, create_branch, etc.)
│   │   ├── gitlab_mcp_client.py      # GitLab API client used by MCP server
│   │   └── __main__.py               # Entrypoint for stdio MCP server
│   │
│   ├── api/                          # HTTP API routes
│   │   ├── webhook_routes.py         # POST /webhooks/gitlab/* (circuit-breaker logic)
│   │   ├── dashboard_routes.py       # GET /api/dashboard/*
│   │   ├── pipeline_routes.py        # GET /api/pipelines/*
│   │   ├── merge_request_routes.py   # GET|POST /api/merge-requests/*
│   │   ├── activity_routes.py        # GET /api/activity/*
│   │   ├── settings_routes.py        # GET|POST|PUT|DELETE /api/settings/*
│   │   ├── websockets_route.py       # WS /ws/{session_id}
│   │   └── debug_route.py            # Dev-only debug endpoint
│   │
│   ├── auth/                         # GitLab OAuth + JWT
│   │   ├── routes.py                 # /auth/gitlab/login, /callback, /logout, /me
│   │   ├── service.py                # GitLabOAuthService (token exchange, user fetch)
│   │   └── schemas.py                # UserResponse, TokenResponse Pydantic models
│   │
│   ├── core/                         # Shared core utilities
│   │   ├── auth.py                   # JWT creation & verification, get_current_user dep
│   │   └── dependencies.py           # Orchestrator singleton factory
│   │
│   ├── db/                           # Data persistence
│   │   ├── mongo_service.py          # MongoDBService: users, projects, events, metrics
│   │   └── neo4j_service.py          # Neo4jService: KB graph driver + schema
│   │
│   ├── observability/                # Pluggable tracing
│   │   ├── base_observability.py     # Abstract observability interface
│   │   └── local_observability.py    # Local/console trace implementation
│   │
│   ├── schemas/                      # Shared Pydantic data models
│   │   ├── pipeline.py               # PipelineFailure
│   │   ├── fix.py                    # FixProposal
│   │   ├── events.py                 # Event
│   │   └── trace.py                  # AgentTrace
│   │
│   └── ws/                           # WebSocket infrastructure
│       └── event_publisher.py        # EventPublisher: broadcasts events to WS clients
│
└── frontend/
    ├── package.json                  # Node.js dependencies
    ├── next.config.mjs               # Next.js configuration
    ├── tsconfig.json                 # TypeScript configuration
    │
    ├── app/                          # Next.js App Router pages
    │   ├── layout.tsx                # Root layout with AuthProvider
    │   ├── page.tsx                  # / → Dashboard (live agent workflow)
    │   ├── pipelines/page.tsx        # /pipelines → Pipeline monitor
    │   ├── merge-requests/page.tsx   # /merge-requests → MR review list
    │   ├── activity/page.tsx         # /activity → Agent activity feed
    │   ├── settings/page.tsx         # /settings → Project and agent config
    │   ├── login/page.tsx            # /login → GitLab OAuth login
    │   └── auth/callback/page.tsx    # /auth/callback → JWT storage
    │
    ├── components/                   # Reusable React components
    │   ├── top-bar.tsx               # Navigation bar with user menu
    │   ├── pipeline-header.tsx       # Pipeline status header card
    │   ├── agent-timeline.tsx        # 8-stage workflow progress sidebar
    │   ├── terminal-ui.tsx           # Live terminal-style log stream
    │   ├── log-panel.tsx             # Structured agent log viewer
    │   ├── merge-request-panel.tsx   # MR approval card with Approve/Reject
    │   ├── merge-request-list.tsx    # Paginated MR list table
    │   ├── pipelines-table.tsx       # Pipeline status table
    │   ├── activity-feed.tsx         # Historical event feed
    │   ├── auth-provider.tsx         # JWT context provider
    │   ├── status-badge.tsx          # Status pill badge component
    │   ├── page-header.tsx           # Page title and subtitle component
    │   └── axolotl-mark.tsx          # Axolotl brand icon component
    │
    └── lib/                          # Frontend utilities
        ├── api.ts                    # Type-safe API client functions
        ├── use-websocket.ts          # useAxolotlSocket React hook
        └── axolotl-data.ts           # Stage definitions and type declarations
```

---

## 🤝 Contributing

We welcome contributions! Please follow the guidelines below.

### Branching Strategy

| Area | Branch |
|---|---|
| AI Agent & Orchestration | `feature/agent-core` |
| GitLab MCP Integration | `feature/gitlab-mcp` |
| Frontend Dashboard | `feature/frontend-dashboard` |
| Observability & Infra | `feature/observability` |

### Merge Rules

- ❌ No direct pushes to `main`
- ✅ All changes go through Merge Requests
- 👀 Minimum **one reviewer** required
- 🤝 Changes to shared schemas (`schemas/`) require **team discussion**
- 🔒 Changes to `orchestrator/pipeline_orchestrator.py` require **Agent Lead review**

### Development Setup

```bash
# Run backend tests
cd backend
pytest tests/ -v

# Run frontend linter
cd frontend
pnpm lint
```

### Commit Convention

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add confidence threshold to agent settings
fix: handle empty pipeline logs gracefully
docs: update API endpoint table
chore: bump gemini-sdk to 0.9.0
```

### Supported Fix Cases (MVP Scope)

Axolotl currently targets three failure categories:

| Error Type | Fix Strategy |
|---|---|
| `ModuleNotFoundError` | Add missing package to `requirements.txt` |
| Formatting Failure | Apply auto-formatter patch (Black) |
| Lint Failure | Apply Gemini-generated lint fix patch |

Failures outside these categories are considered out-of-scope for the current MVP.

---

## 📄 License

This project is licensed under the **MIT License**.

```
MIT License

Copyright (c) 2026 Axolotl Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

<div align="center">

Built with ❤️ and 🦎 by the Axolotl Team

*"A self-healing CI/CD pipeline with human approval and full observability."*

</div>
