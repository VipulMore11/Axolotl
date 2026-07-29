"""
GitLab MCP Server
Exposes GitLab operations as tools via the Model Context Protocol using stdio transport.
The AI agent connects to this server to perform GitLab operations.
"""

import asyncio
import sys
from typing import Any
from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult
import json

from dotenv import load_dotenv
load_dotenv()

# ── CRITICAL: Redirect print() to stderr ────────────────────────────
# This module runs as an MCP server over stdio transport.
# stdout is reserved for JSON-RPC protocol messages.
# Any print() to stdout corrupts the protocol stream and breaks the client.
import builtins
_original_print = builtins.print

def _stderr_print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    _original_print(*args, **kwargs)

builtins.print = _stderr_print

from db.mongo_service import get_mongo_service
from .gitlab_mcp_client import GitLabMCPClient


# Initialize server
server = Server("axolotl-gitlab-mcp")

# Global state
mongo_service = None
gitlab_client = None


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools."""
    return [
        Tool(
            name="get_pipeline_logs",
            description="Fetch logs for all failed jobs in a GitLab pipeline. Use this to analyze why a pipeline failed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "GitLab project ID"
                    },
                    "pipeline_id": {
                        "type": "string",
                        "description": "GitLab pipeline ID"
                    }
                },
                "required": ["project_id", "pipeline_id"]
            }
        ),
        Tool(
            name="create_branch",
            description="Create a new fix branch in the repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "GitLab project ID"
                    },
                    "source_branch": {
                        "type": "string",
                        "description": "Source branch to branch from (e.g., 'main')"
                    },
                    "new_branch_name": {
                        "type": "string",
                        "description": "Name of the new branch to create"
                    }
                },
                "required": ["project_id", "source_branch", "new_branch_name"]
            }
        ),
        Tool(
            name="get_file_contents",
            description="Fetch the raw contents of a file at a given branch. Returns exists=false when the file is missing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "GitLab project ID"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch or ref to read from"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file in the repository"
                    }
                },
                "required": ["project_id", "branch", "file_path"]
            }
        ),
        Tool(
            name="search_code",
            description=(
                "Search repository file contents for literal patterns. Used to find "
                "sibling files that share the same CI error signature (fan-out)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "GitLab project ID"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch or ref to search"
                    },
                    "patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Literal substrings to find in file contents"
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Max files to open while scanning (default 200)"
                    },
                    "max_matches": {
                        "type": "integer",
                        "description": "Stop after this many matching files (default 50)"
                    }
                },
                "required": ["project_id", "branch", "patterns"]
            }
        ),
        Tool(
            name="update_file",
            description="Update or create a file and commit the changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "GitLab project ID"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch to commit to"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file in the repository"
                    },
                    "content": {
                        "type": "string",
                        "description": "New file content"
                    },
                    "commit_message": {
                        "type": "string",
                        "description": "Commit message"
                    }
                },
                "required": ["project_id", "branch", "file_path", "content", "commit_message"]
            }
        ),
        Tool(
            name="create_merge_request",
            description="Create a merge request to propose the fix.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "GitLab project ID"
                    },
                    "source_branch": {
                        "type": "string",
                        "description": "Source branch (the fix branch)"
                    },
                    "target_branch": {
                        "type": "string",
                        "description": "Target branch (usually the branch that failed)"
                    },
                    "title": {
                        "type": "string",
                        "description": "Merge request title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Merge request description"
                    }
                },
                "required": ["project_id", "source_branch", "target_branch", "title", "description"]
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    """Handle tool calls."""
    print(f"[DEBUG] mcp_server.call_tool called | name={name}")

    if not gitlab_client:
        print("[ERROR] GitLab client not initialized")
        return CallToolResult(
            content=[TextContent(type="text", text="Error: GitLab client not initialized")],
            isError=True
        )

    try:
        if name == "get_pipeline_logs":
            try:
                result = await gitlab_client.get_pipeline_logs(
                    arguments["project_id"],
                    arguments["pipeline_id"]
                )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                return CallToolResult(
                    content=[TextContent(type="text", text=f"get_pipeline_logs exception: {e}\n{tb}")],
                    isError=True
                )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="get_pipeline_logs returned None — client returned no data (check MongoDB project config, GitLab auth, or pipeline ID)")],
                    isError=True
                )

        elif name == "create_branch":
            try:
                result = await gitlab_client.create_branch(
                    arguments["project_id"],
                    arguments["source_branch"],
                    arguments["new_branch_name"]
                )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                return CallToolResult(
                    content=[TextContent(type="text", text=f"create_branch exception: {e}\n{tb}")],
                    isError=True
                )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="create_branch returned None — check GitLab auth and branch permissions")],
                    isError=True
                )

        elif name == "get_file_contents":
            try:
                result = await gitlab_client.get_file_contents(
                    arguments["project_id"],
                    arguments["branch"],
                    arguments["file_path"]
                )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                return CallToolResult(
                    content=[TextContent(type="text", text=f"get_file_contents exception: {e}\n{tb}")],
                    isError=True
                )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="get_file_contents returned None — check GitLab auth and project config")],
                    isError=True
                )

        elif name == "search_code":
            try:
                result = await gitlab_client.search_code(
                    arguments["project_id"],
                    arguments["branch"],
                    list(arguments.get("patterns") or []),
                    max_files=int(arguments.get("max_files") or 200),
                    max_matches=int(arguments.get("max_matches") or 50),
                )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                return CallToolResult(
                    content=[TextContent(type="text", text=f"search_code exception: {e}\n{tb}")],
                    isError=True
                )
            if result is not None:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="search_code returned None — check GitLab auth and project config")],
                    isError=True
                )

        elif name == "update_file":
            try:
                result = await gitlab_client.update_file(
                    arguments["project_id"],
                    arguments["branch"],
                    arguments["file_path"],
                    arguments["content"],
                    arguments["commit_message"]
                )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                return CallToolResult(
                    content=[TextContent(type="text", text=f"update_file exception: {e}\n{tb}")],
                    isError=True
                )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="update_file returned None — check branch exists and file path")],
                    isError=True
                )

        elif name == "create_merge_request":
            try:
                result = await gitlab_client.create_merge_request(
                    arguments["project_id"],
                    arguments["source_branch"],
                    arguments["target_branch"],
                    arguments["title"],
                    arguments["description"]
                )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                return CallToolResult(
                    content=[TextContent(type="text", text=f"create_merge_request exception: {e}\n{tb}")],
                    isError=True
                )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="create_merge_request returned None — check branches exist and MR permissions")],
                    isError=True
                )

        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True
            )

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        return CallToolResult(
            content=[TextContent(type="text", text=f"Unexpected error in call_tool: {e}\n{tb}")],
            isError=True
        )


async def main():
    """Main entry point for the MCP server."""
    global mongo_service, gitlab_client

    print("Starting Axolotl GitLab MCP Server...")

    try:
        # Initialize MongoDB service
        mongo_service = get_mongo_service()
        await mongo_service.connect()

        # Initialize GitLab client
        gitlab_client = GitLabMCPClient(mongo_service)

        print("Successfully initialized MongoDB and GitLab client")

        # Run the server with stdio transport
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            print("GitLab MCP Server is running on stdio transport")
            await server.run(read_stream, write_stream, server.create_initialization_options())

    except Exception as e:
        print(f"Failed to start MCP server: {e}")
        raise

    finally:
        if mongo_service:
            await mongo_service.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
