I will output exactly the updated TRD per instructions and Rule 1.

```markdown
# Technical Requirements Document (TRD): 8-Stage Agentic CI Fix Pipeline

## 1. Overview & Objectives
Refactor the existing webhook-driven LangGraph CI-fix agent into an 8-stage, multi-agent pipeline based on the "Evaluator-Optimizer" and "Artifact Contract" design patterns[cite: 1]. 

The system relies on specialized personas communicating via strict structured schemas, avoiding large conversational transcripts[cite: 1].

**Target Graph Flow:**
1. `workspace_setup`
2. `requirements_analysis` (Includes Knowledge Base Graph Grounding)
3. `technical_architecture`
4. `task_breakdown`
5. `code_implementation` (Loop target from 6 & 7)
6. `testing_validation` (Routes to 7 on pass, 5 on fail)
7. `code_review` (Routes to END on pass, 5 on fail)
8. `git_operations_MCP` (Outside LangGraph core loop)

---

## 2. State & Schema Definitions (Artifact Contracts)
**File to Update:** `backend/agents/ci_fix_state.py`

Replace loose strings with strict schemas to enforce "Artifact Contracts" between nodes[cite: 1]. We are updating the schema to support **multi-file edits** instead of a single file MVP.

```python
from typing import TypedDict, Optional, List, Dict

class FilePatch(TypedDict):
    file_path: str
    updated_content: str

class ArchitecturePlan(TypedDict):
    strategy_type: str  # e.g., "deps", "lint", "format", "code_patch"
    affected_files: List[str] # List of all files requiring edits
    proposed_solution: str

class CritiqueResult(TypedDict):
    satisfactory: bool
    issues: List[str]  # Must cite specific line numbers and files
    revision_instructions: List[str]

class CIFixState(TypedDict):
    # Existing fields
    pipeline_id: str
    ci_logs: str
    root_cause: str
    commit_message: str
    attempts: int
    
    # New Multi-File Artifacts
    file_patches: List[FilePatch]
    
    # New Orchestration Artifacts
    architecture_plan: ArchitecturePlan
    task_breakdown: List[str]
    validation_failures: List[str]
    review_history: List[CritiqueResult]
    review_approved: bool
    current_stage: str

```

---

## 3. Knowledge Base Integration

**File to Create:** `backend/agents/knowledge_schema.py`

Implement a persistent knowledge layer to support the pipeline and reason across different CI pipeline sessions.

**Nodes Types:**

* `Entity`: Code components (e.g., specific files, libraries, dependencies).


* `Claim`: The diagnosed `root_cause` of a failure.


* `Source`: The CI log transcript or the `pipeline_id`.


* `Artifact`: The `FixProposal` or generated code patch.


* `Run`: The execution record of the LangGraph agent.



**Edge Types:**

* `mentions`, `supports`, `contradicts`, `derived_from`, `supersedes`.



---

## 4. Node Logic & Persona Prompts

**File to Update:** `backend/agents/langgraph_ci_fix_agent.py`

Rebuild the graph nodes. Apply distinct roles and "Preserve Successful Work" principles.

### A. Stage 1 & 2 (Setup & Analysis)

* **workspace_setup:** Reset Docker workspace. Seed messages with project/pipeline/branch.
* **requirements_analysis:** Extract `root_cause` from logs. **Graph Grounding:** Query the Knowledge Base for historical `Claim` nodes matching the error. If found, inject the historical successful `Artifact` into the context to ground the plan.


* *Model Requirement:* Use **Gemini Flash** (fast/cheap) for extraction and context routing.



### B. Stage 3 (technical_architecture)

* **Persona:** *Architect Agent*. Focuses on planning, low-blast-radius fixes, and compatibility.


* **Action:** Analyzes `root_cause` and outputs the `ArchitecturePlan` JSON artifact. Ensures `affected_files` lists every file needing modification.
* *Model Requirement:* Use **Gemini Pro**.

### C. Stage 4 (task_breakdown)

* **Persona:** *Tech Lead Agent*. Focuses on execution order and dependencies.


* **Action:** Converts `ArchitecturePlan` into an ordered list of strings (`task_breakdown`).
* *Model Requirement:* Use **Gemini Flash**.

### D. Stage 5 (code_implementation)

* **Persona:** *Developer Agent*. Focuses on syntax and functionality.


* **Action:** Takes `task_breakdown` and outputs an array of `file_patches` (multi-file support) and a single `commit_message`.
* **Replan Rule:** If `validation_failures` or `review_history` exist, apply a *targeted revision* to the existing `file_patches` rather than rewriting from scratch.


* *Model Requirement:* Use **Gemini Pro**.

### E. Stage 6 (testing_validation)

* **Action:** Call `validate_patch` (Docker checks). Bump `attempts`. Append errors to `validation_failures`.
* **Routing:** If pass -> `code_review`. If fail & `attempts` < MAX -> `code_implementation`. Else -> Fail closed.

### F. Stage 7 (code_review)

* **Persona:** *Evaluator Agent*. Focuses on strict adherence to the Architect's plan.


* **Action:** Compare `file_patches` against `root_cause` and `architecture_plan`. Produce `CritiqueResult`.
* **Rule:** The critique must cite specific line numbers/files and generate concrete `revision_instructions` before returning `satisfactory: false`.


* **Routing:** If `satisfactory: true` -> `END`. If false -> route back to `code_implementation` with the feedback.


* *Model Requirement:* Use **Gemini Pro**.

---

## 5. UI & Orchestrator Glue

**Files to Update:**

* `backend/orchestrator/event_types.py`
* `backend/orchestrator/pipeline_orchestrator.py`

1. **Callback System:** Inject an `on_stage(stage_name, message, metadata)` callback into the LangGraph setup. Call this at the start of every node to stream real-time events to the UI.
2. **Event Definitions:** Add new stage constants: `workspace_setup`, `requirements_analysis`, `technical_architecture`, `task_breakdown`, `code_implementation`, `testing_validation`, `code_review`, `git_operations`.
3. **Git Operations (Stage 8):** After LangGraph exits, emit the `git_operations` event once. Iterate over all `file_patches` array and call the MCP `update_file` tool for **each** file, then create a single Merge Request. Keep MCP calls as metadata or sub-messages within this event.
4. **Knowledge Extraction (Post-HITL):** Create a webhook handler for `merge_request_approved`. Once human-approved, trigger an extraction agent to write the successful `CIFixState` into the Knowledge Base. Ensure the write is additive (link with `supersedes` if a previous fix existed) and retains its provenance (linked to pipeline run).



---

## 6. Instructions for Cursor

1. **Iterative Multi-File Updates:** Ensure Stage 8 correctly loops over all patches generated in Stage 5. Do not hardcode a single file string for MCP `update_file`.
2. **Preserve Tracing:** Ensure `@traceable` and LangSmith `run_config` tags map correctly to the new stage names.
3. **Knowledge Base Logic:** Keep the DB write operations asynchronous (post-merge approval) so the core pipeline graph stays fast.

```

```