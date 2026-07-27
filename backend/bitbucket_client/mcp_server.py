"""
Bitbucket MCP Server
Exposes Bitbucket operations as tools via the Model Context Protocol using stdio transport.
The AI agent connects to this server to perform Bitbucket operations.

Tool interface is identical to the GitLab MCP Server so the orchestrator
can use either server interchangeably.
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
from .bitbucket_api_client import BitbucketAPIClient


# Initialize server
server = Server("axolotl-bitbucket-mcp")

# Global state
mongo_service = None
bitbucket_client = None


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List available tools.

    Tool names match the GitLab MCP server exactly so the orchestrator
    can call them interchangeably.
    """
    return [
        Tool(
            name="get_pipeline_logs",
            description="Fetch logs for all failed steps in a Bitbucket pipeline. Use this to analyze why a pipeline failed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Internal project ID (from MongoDB)"
                    },
                    "pipeline_id": {
                        "type": "string",
                        "description": "Bitbucket pipeline UUID"
                    }
                },
                "required": ["project_id", "pipeline_id"]
            }
        ),
        Tool(
            name="create_branch",
            description="Create a new fix branch in the Bitbucket repository.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Internal project ID (from MongoDB)"
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
                        "description": "Internal project ID (from MongoDB)"
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
            name="update_file",
            description="Update or create a file and commit the changes to Bitbucket.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Internal project ID (from MongoDB)"
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
            description="Create a pull request on Bitbucket to propose the fix.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Internal project ID (from MongoDB)"
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
                        "description": "Pull request title"
                    },
                    "description": {
                        "type": "string",
                        "description": "Pull request description"
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

    if not bitbucket_client:
        print("[ERROR] Bitbucket client not initialized")
        return CallToolResult(
            content=[TextContent(type="text", text="Error: Bitbucket client not initialized")],
            isError=True
        )

    try:
        if name == "get_pipeline_logs":
            try:
                result = await bitbucket_client.get_pipeline_logs(
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
                    content=[TextContent(type="text", text="get_pipeline_logs returned None — no data (check MongoDB config, Bitbucket auth, or pipeline UUID)")],
                    isError=True
                )

        elif name == "create_branch":
            try:
                result = await bitbucket_client.create_branch(
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
                    content=[TextContent(type="text", text="create_branch returned None — check Bitbucket auth and branch permissions")],
                    isError=True
                )

        elif name == "get_file_contents":
            try:
                result = await bitbucket_client.get_file_contents(
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
                    content=[TextContent(type="text", text="get_file_contents returned None — check Bitbucket auth and repo path")],
                    isError=True
                )

        elif name == "update_file":
            try:
                result = await bitbucket_client.update_file(
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
                # The orchestrator uses "create_merge_request" as the tool name
                # We map it to Bitbucket's pull request creation
                result = await bitbucket_client.create_pull_request(
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
                    content=[TextContent(type="text", text=f"create_merge_request (pull request) exception: {e}\n{tb}")],
                    isError=True
                )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="create_merge_request returned None — check branches exist and PR permissions")],
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
    global mongo_service, bitbucket_client

    print("Starting Axolotl Bitbucket MCP Server...")

    try:
        # Initialize MongoDB service
        mongo_service = get_mongo_service()
        await mongo_service.connect()

        # Initialize Bitbucket client
        bitbucket_client = BitbucketAPIClient(mongo_service)

        print("Successfully initialized MongoDB and Bitbucket client")

        # Run the server with stdio transport
        # pyrefly: ignore [missing-import]
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read_stream, write_stream):
            print("Bitbucket MCP Server is running on stdio transport")
            await server.run(read_stream, write_stream, server.create_initialization_options())

    except Exception as e:
        print(f"Failed to start MCP server: {e}")
        raise

    finally:
        if mongo_service:
            await mongo_service.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
