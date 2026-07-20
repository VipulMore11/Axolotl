"""
Allows running the Bitbucket MCP server as a module:
    python -m bitbucket_client
"""

import asyncio
from .mcp_server import main

asyncio.run(main())
