"""Allow running the MCP server as: python -m gitlab_client.mcp_server"""

import asyncio
from gitlab_client.mcp_server import main

if __name__ == "__main__":
    asyncio.run(main())
