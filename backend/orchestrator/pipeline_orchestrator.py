"""
Pipeline Orchestrator
Central workflow controller that coordinates the full pipeline fix lifecycle:
  Webhook → Fetch Logs (MCP) → AI Analysis → Create Branch (MCP) → Commit Fix (MCP) → Create MR (MCP)

Uses the MCP client to communicate with the GitLab MCP Server via stdio transport,
giving the AI agent access to GitLab tools.
"""

import asyncio
import json
import os
import pathlib
import sys
from datetime import datetime, UTC
from typing import Optional

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from agents.ci_fix_agent import CIFixAgent, CIFixAgentError
from db.mongo_service import MongoDBService
from orchestrator.event_types import EventType
from schemas.events import Event
from schemas.fix import FixProposal
from schemas.pipeline import PipelineFailure
from schemas.trace import AgentTrace
from core.pendo_track import pendo_track
from ws.event_publisher import EventPublisher


class PipelineOrchestrator:
    """
    Coordinates pipeline failure analysis and fix proposal generation.
    Connects to the GitLab MCP Server to perform Git operations.
    """

    def __init__(
        self,
        ci_fix_agent: Optional[CIFixAgent] = None,
        event_publisher: Optional[EventPublisher] = None,
        mongo_service: Optional[MongoDBService] = None,
    ) -> None:
        self.ci_fix_agent = ci_fix_agent or CIFixAgent()
        self.event_publisher = event_publisher
        self.mongo_service = mongo_service
        self.current_user_id: Optional[str] = None

    # ─── Event Publishing (bridges Person 4's EventPublisher) ───────

    async def _publish_event(
        self,
        event_type: EventType,
        message: str,
        session_id: str = "system",
        metadata: Optional[dict] = None,
    ) -> None:
        """Publish an orchestration event to WebSocket clients, observability, and MongoDB."""
        print(f"[EVENT] {event_type.value}: {message}")

        event = Event(
            timestamp=datetime.now(UTC),
            session_id=session_id,
            user_id=self.current_user_id,
            event_type=event_type.value,
            message=message,
            metadata=metadata,
        )

        # Persist to MongoDB for the Activity page
        if self.mongo_service:
            try:
                await self.mongo_service.log_event(event.model_dump())
            except Exception as e:
                print(f"[EVENT] Failed to persist event: {e}")

        if self.event_publisher:
            await self.event_publisher.publish(event)

    # ─── MCP Client Connection ──────────────────────────────────────

    async def _call_mcp_tool(
        self,
        session: ClientSession,
        tool_name: str,
        arguments: dict,
    ) -> Optional[dict]:
        """
        Call a tool on the GitLab MCP Server and return the parsed result.

        Args:
            session: Active MCP client session
            tool_name: Name of the MCP tool to call
            arguments: Tool arguments dictionary

        Returns:
            Parsed JSON result dict, or None on failure
        """
        print(f"[DEBUG] _call_mcp_tool | tool={tool_name} | args={arguments}")
        try:
            result = await session.call_tool(tool_name, arguments)
            print(f"[DEBUG] _call_mcp_tool | tool={tool_name} | result type={type(result).__name__}")

            if result.isError:
                error_text = result.content[0].text if result.content else "Unknown error"
                print(f"[MCP ERROR] {tool_name}: {error_text}")
                return None

            # Parse the JSON text response
            print(f"[DEBUG] Raw MCP response: {result}")    
            text = result.content[0].text if result.content else "{}"
            print(f"[DEBUG] _call_mcp_tool | tool={tool_name} | text length={len(text)}")
            parsed = json.loads(text)
            print(f"[DEBUG] _call_mcp_tool | tool={tool_name} | parsed keys={list(parsed.keys()) if isinstance(parsed, dict) else 'not-a-dict'}")
            return parsed

        except json.JSONDecodeError as e:
            raw = result.content[0].text if result.content else ""
            print(f"[MCP ERROR] {tool_name}: JSON decode failed: {e}")
            print(f"[MCP ERROR] {tool_name}: Raw text was: {raw[:500]}")
            # Tool returned non-JSON text — return as raw string
            return {"raw_response": raw}
        except Exception as e:
            print(f"[MCP ERROR] Failed to call {tool_name}: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

    # ─── Full Pipeline Fix Workflow ─────────────────────────────────

    async def handle_pipeline_failure(
        self,
        project_id: str,
        pipeline_id: str,
        branch: str,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        Run the complete pipeline fix workflow using MCP tools.

        Flow:
          1. Publish "Pipeline failed" event
          2. Fetch pipeline logs via MCP `get_pipeline_logs`
          3. Analyze logs with CIFixAgent (Gemini)
          4. Create fix branch via MCP `create_branch`
          5. Commit the fix via MCP `update_file`
          6. Create merge request via MCP `create_merge_request`
          7. Publish "Awaiting approval" event

        Args:
            project_id: GitLab project ID
            pipeline_id: GitLab pipeline ID
            branch: Branch that failed
            user_id: The user associated with this project

        Returns:
            Summary dict with workflow result
        """
        self.current_user_id = user_id
        session_id = f"pipeline-{pipeline_id}"
        fix_branch = f"axolotl/fix/{pipeline_id}"

        print(f"[DEBUG] handle_pipeline_failure called | project_id={project_id} | pipeline_id={pipeline_id} | branch={branch}")

        await self._publish_event(
            EventType.PIPELINE_FAILED,
            f"Pipeline {pipeline_id} failed on branch '{branch}'.",
            session_id=session_id,
            metadata={"project_id": project_id, "pipeline_id": pipeline_id, "branch": branch},
        )

        # Determine the Python executable path to launch the MCP server
        python_exe = sys.executable

        # Determine project root (where .env and packages live)
        project_root = str(pathlib.Path(__file__).resolve().parent.parent)

        # Connect to GitLab MCP Server via stdio
        # Pass the full environment so the subprocess inherits MONGODB_CONNECTION_STRING etc.
        server_params = StdioServerParameters(
            command=python_exe,
            args=["-m", "gitlab_client.mcp_server"],
            cwd=project_root,
            env={**os.environ},
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                # Initialize the MCP session
                await session.initialize()

                # Discover available tools (for logging/debugging)
                tools = await session.list_tools()
                tool_names = [t.name for t in tools.tools]
                print(f"[DEBUG] MCP Session Initialized. Available tools: {tool_names}")

                # ── Step 1: Fetch pipeline logs ─────────────────────
                print(f"[DEBUG] Fetching logs for pipeline {pipeline_id}")
                await self._publish_event(
                    EventType.FETCHING_LOGS,
                    f"Fetching logs for pipeline {pipeline_id}...",
                    session_id=session_id,
                )

                logs_result = await self._call_mcp_tool(session, "get_pipeline_logs", {
                    "project_id": project_id,
                    "pipeline_id": pipeline_id,
                })
                print(f"[DEBUG] get_pipeline_logs returned: {logs_result}")

                if not logs_result or not logs_result.get("failed_jobs"):
                    await self._publish_event(
                        EventType.FIX_FAILED,
                        "Could not retrieve pipeline logs or no failed jobs found.",
                        session_id=session_id,
                    )
                    await pendo_track(
                        event="pipeline_fix_failed",
                        visitor_id=user_id,
                        account_id=user_id,
                        properties={
                            "project_id": project_id,
                            "pipeline_id": pipeline_id,
                            "failure_reason": "no_logs",
                            "failed_step": "fetch_logs",
                        },
                    )
                    return {"status": "failed", "reason": "no_logs"}

                # Combine all job traces into a single log string
                combined_logs = "\n\n".join(
                    f"--- Job: {job['job_name']} (stage: {job['stage']}) ---\n{job['trace']}"
                    for job in logs_result["failed_jobs"]
                )

                # ── Step 2: Analyze with AI Agent ───────────────────
                await self._publish_event(
                    EventType.ANALYZING,
                    "Analyzing root cause with AI agent...",
                    session_id=session_id,
                )

                failure = PipelineFailure(
                    project_id=project_id,
                    pipeline_id=pipeline_id,
                    branch=branch,
                    logs=combined_logs,
                )

                try:
                    print(f"[DEBUG] Calling ci_fix_agent.analyze")
                    fix: FixProposal = await self.ci_fix_agent.analyze(failure)
                    print(f"[DEBUG] ci_fix_agent.analyze returned successfully")
                except CIFixAgentError as e:
                    print(f"[DEBUG] ci_fix_agent.analyze raised error: {e}")
                    await self._publish_event(
                        EventType.FIX_FAILED,
                        f"AI analysis failed: {e}",
                        session_id=session_id,
                    )
                    await pendo_track(
                        event="pipeline_fix_failed",
                        visitor_id=user_id,
                        account_id=user_id,
                        properties={
                            "project_id": project_id,
                            "pipeline_id": pipeline_id,
                            "failure_reason": str(e)[:200],
                            "failed_step": "ai_analysis",
                        },
                    )
                    return {"status": "failed", "reason": str(e)}

                await self._publish_event(
                    EventType.GENERATING_FIX,
                    f"Root cause: {fix.root_cause}. Fix target: {fix.file_path}",
                    session_id=session_id,
                    metadata={"root_cause": fix.root_cause, "file_path": fix.file_path},
                )

                # Log the agent trace for observability
                if self.event_publisher and self.event_publisher.observability:
                    trace = AgentTrace(
                        session_id=session_id,
                        input_data=combined_logs[:500],  # Truncate for readability
                        reasoning=fix.root_cause,
                        output_data=fix.commit_message,
                    )
                    await self.event_publisher.observability.create_trace(trace)

                # ── Step 3: Create fix branch ───────────────────────
                await self._publish_event(
                    EventType.CREATING_BRANCH,
                    f"Creating branch '{fix_branch}' from '{branch}'...",
                    session_id=session_id,
                )

                branch_result = await self._call_mcp_tool(session, "create_branch", {
                    "project_id": project_id,
                    "source_branch": branch,
                    "new_branch_name": fix_branch,
                })
                print(f"[DEBUG] create_branch returned: {branch_result is not None}")

                if not branch_result:
                    await self._publish_event(
                        EventType.FIX_FAILED,
                        f"Failed to create branch '{fix_branch}'.",
                        session_id=session_id,
                    )
                    await pendo_track(
                        event="pipeline_fix_failed",
                        visitor_id=user_id,
                        account_id=user_id,
                        properties={
                            "project_id": project_id,
                            "pipeline_id": pipeline_id,
                            "failure_reason": "branch_creation_failed",
                            "failed_step": "create_branch",
                        },
                    )
                    return {"status": "failed", "reason": "branch_creation_failed"}

                # ── Step 4: Commit the fix ──────────────────────────
                await self._publish_event(
                    EventType.COMMITTING,
                    f"Committing fix to {fix.file_path}...",
                    session_id=session_id,
                )

                update_result = await self._call_mcp_tool(session, "update_file", {
                    "project_id": project_id,
                    "branch": fix_branch,
                    "file_path": fix.file_path,
                    "content": fix.updated_content,
                    "commit_message": fix.commit_message,
                })
                print(f"[DEBUG] update_file returned: {update_result is not None}")

                if not update_result:
                    await self._publish_event(
                        EventType.FIX_FAILED,
                        f"Failed to commit fix to {fix.file_path}.",
                        session_id=session_id,
                    )
                    await pendo_track(
                        event="pipeline_fix_failed",
                        visitor_id=user_id,
                        account_id=user_id,
                        properties={
                            "project_id": project_id,
                            "pipeline_id": pipeline_id,
                            "failure_reason": "commit_failed",
                            "failed_step": "commit_fix",
                        },
                    )
                    return {"status": "failed", "reason": "commit_failed"}

                # ── Step 5: Create merge request ────────────────────
                await self._publish_event(
                    EventType.CREATING_MR,
                    "Creating merge request...",
                    session_id=session_id,
                )

                mr_description = (
                    f"## 🦎 Axolotl Auto-Fix\n\n"
                    f"**Root Cause:** {fix.root_cause}\n\n"
                    f"**File Changed:** `{fix.file_path}`\n\n"
                    f"**Pipeline:** {pipeline_id}\n\n"
                    f"**Branch:** {branch}\n\n"
                    f"---\n"
                    f"_This merge request was automatically generated by Axolotl._\n"
                    f"_Please review and approve to deploy the fix._"
                )

                mr_result = await self._call_mcp_tool(session, "create_merge_request", {
                    "project_id": project_id,
                    "source_branch": fix_branch,
                    "target_branch": branch,
                    "title": f"🦎 Axolotl Fix: {fix.commit_message}",
                    "description": mr_description,
                })
                print(f"[DEBUG] create_merge_request returned: {mr_result is not None}")

                if not mr_result:
                    await self._publish_event(
                        EventType.FIX_FAILED,
                        "Failed to create merge request.",
                        session_id=session_id,
                    )
                    await pendo_track(
                        event="pipeline_fix_failed",
                        visitor_id=user_id,
                        account_id=user_id,
                        properties={
                            "project_id": project_id,
                            "pipeline_id": pipeline_id,
                            "failure_reason": "mr_creation_failed",
                            "failed_step": "create_mr",
                        },
                    )
                    return {"status": "failed", "reason": "mr_creation_failed"}

                # ── Step 6: Success ─────────────────────────────────
                await self._publish_event(
                    EventType.WAITING_APPROVAL,
                    f"Merge request created! Awaiting human approval. URL: {mr_result.get('web_url', 'N/A')}",
                    session_id=session_id,
                    metadata=mr_result,
                )

                await pendo_track(
                    event="pipeline_fix_completed",
                    visitor_id=user_id,
                    account_id=user_id,
                    properties={
                        "project_id": project_id,
                        "pipeline_id": pipeline_id,
                        "branch": branch,
                        "fix_branch": fix_branch,
                        "root_cause": fix.root_cause[:200],
                        "file_path": fix.file_path,
                        "commit_message": fix.commit_message[:200],
                        "mr_web_url": mr_result.get("web_url", ""),
                    },
                )

                return {
                    "status": "success",
                    "project_id": project_id,
                    "pipeline_id": pipeline_id,
                    "branch": branch,
                    "fix_branch": fix_branch,
                    "fix": {
                        "root_cause": fix.root_cause,
                        "file_path": fix.file_path,
                        "commit_message": fix.commit_message,
                    },
                    "merge_request": mr_result,
                }
