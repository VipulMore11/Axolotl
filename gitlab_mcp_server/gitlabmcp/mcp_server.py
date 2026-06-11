"""
GitLab MCP Server
Exposes GitLab operations as tools via the Model Context Protocol using stdio transport.
"""

import asyncio
from typing import Any
from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult
import json

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
    
    if not gitlab_client:
        return CallToolResult(
            content=[TextContent(type="text", text="Error: GitLab client not initialized")],
            isError=True
        )
    
    try:
        if name == "get_pipeline_logs":
            result = await gitlab_client.get_pipeline_logs(
                arguments["project_id"],
                arguments["pipeline_id"]
            )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="Failed to fetch pipeline logs")],
                    isError=True
                )
        
        elif name == "create_branch":
            result = await gitlab_client.create_branch(
                arguments["project_id"],
                arguments["source_branch"],
                arguments["new_branch_name"]
            )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="Failed to create branch")],
                    isError=True
                )
        
        elif name == "update_file":
            result = await gitlab_client.update_file(
                arguments["project_id"],
                arguments["branch"],
                arguments["file_path"],
                arguments["content"],
                arguments["commit_message"]
            )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="Failed to update file")],
                    isError=True
                )
        
        elif name == "create_merge_request":
            result = await gitlab_client.create_merge_request(
                arguments["project_id"],
                arguments["source_branch"],
                arguments["target_branch"],
                arguments["title"],
                arguments["description"]
            )
            if result:
                return CallToolResult(
                    content=[TextContent(type="text", text=json.dumps(result, indent=2))],
                    isError=False
                )
            else:
                return CallToolResult(
                    content=[TextContent(type="text", text="Failed to create merge request")],
                    isError=True
                )
        
        else:
            return CallToolResult(
                content=[TextContent(type="text", text=f"Unknown tool: {name}")],
                isError=True
            )
    
    except Exception as e:
        return CallToolResult(
            content=[TextContent(type="text", text=f"Error: {str(e)}")],
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
        
        # Run the server
        async with server:
            print("GitLab MCP Server is running on stdio transport")
            await server.wait_for_shutdown()
    
    except Exception as e:
        print(f"Failed to start MCP server: {e}")
        raise
    
    finally:
        if mongo_service:
            await mongo_service.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
