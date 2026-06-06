"""
Webhook Server Entry Point
Start the FastAPI webhook server to receive GitLab events.
"""

import uvicorn
import sys

from api.webhook_routes import app


def run_webhook_server(host: str = "0.0.0.0", port: int = 8000, reload: bool = True):
    """
    Run the webhook server.
    
    Args:
        host: Server host
        port: Server port
        reload: Enable auto-reload on code changes
    """
    print(f"Starting Axolotl Webhook Server on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    run_webhook_server(port=port)
