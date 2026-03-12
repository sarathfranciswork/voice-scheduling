"""
FastAPI application entry point.

Serves the React frontend, REST API, and WebSocket chat endpoint.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import database as db
from app import mcp_bridge
from app.config import API_HOST, API_PORT
from app.routes.auth import router as auth_router
from app.routes.chat_ws import router as chat_ws_router
from app.routes.conversations import router as conversations_router
from app.routes.realtime import router as realtime_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting up: initializing database and MCP bridge")
    await db.init_db()
    try:
        await mcp_bridge.connect()
    except Exception:
        logger.warning("MCP server not available at startup -- tools will be unavailable until it connects")
    yield
    logger.info("Shutting down")
    await mcp_bridge.disconnect()
    await db.close_db()


app = FastAPI(
    title="CVS Vaccine Scheduling Assistant",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(auth_router)
app.include_router(conversations_router)
app.include_router(chat_ws_router)
app.include_router(realtime_router)


# Serve built React frontend
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:
    logger.warning(f"Frontend build not found at {FRONTEND_DIR} -- run 'npm run build' in frontend/")


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=API_HOST,
        port=API_PORT,
        reload=True,
        log_level="info",
    )
