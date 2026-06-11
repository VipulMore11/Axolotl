"""
Axolotl — Autonomous CI/CD Pipeline Fixer
Main FastAPI application entry point.

Combines all routers:
  - WebSocket endpoint (Person 4)
  - Debug/test routes (Person 4)
  - GitLab webhook routes (Person 2)
  - Health check

Manages MongoDB lifecycle on startup/shutdown.
"""

from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.debug_route import router as debug_router
from api.websockets_route import router as websocket_router
from api.webhook_routes import router as webhook_router
from auth.routes import router as auth_router
from db.mongo_service import get_mongo_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Connects to MongoDB on startup, disconnects on shutdown.
    """
    # ── Startup ──
    mongo = get_mongo_service()
    await mongo.connect()
    print("Axolotl backend started.")
    yield
    # ── Shutdown ──
    await mongo.disconnect()
    print("Axolotl backend stopped.")


app = FastAPI(
    title="Axolotl",
    description="Autonomous CI/CD Pipeline Fixer — self-healing pipelines with human approval and full observability.",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS (for future frontend) ──────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Lock down in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────────
app.include_router(debug_router)
app.include_router(websocket_router)
app.include_router(webhook_router)
app.include_router(auth_router)


# ── Health Check ─────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "axolotl"}


@app.get("/", tags=["system"])
async def root():
    """Root endpoint."""
    return {
        "name": "Axolotl",
        "version": "1.0.0",
        "description": "Autonomous CI/CD Pipeline Fixer",
    }

