"""
REST API endpoints for CVS authentication (redirect-based login flow).

These endpoints drive the "Login via CVS" button in the frontend:
  1. POST /api/auth/start-login  -- opens CVS in Playwright browser
  2. GET  /api/auth/status        -- polls for auth completion
  3. POST /api/auth/logout        -- clears auth state
"""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException

from app import mcp_bridge
from app.config import set_auth_state

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/start-login")
async def start_login():
    """Open CVS login in browser for the user to complete manually."""
    try:
        result = await mcp_bridge.call_tool("start_manual_login", {})
        return json.loads(result)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="MCP server not connected")
    except Exception as e:
        logger.error("start-login failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def login_status():
    """Poll whether the user has completed login in the browser."""
    try:
        result = await mcp_bridge.call_tool("check_login_status", {})
        data = json.loads(result)
        if data.get("status") == "authenticated":
            set_auth_state(authenticated=True, profile=data.get("profile"))
        return data
    except RuntimeError:
        raise HTTPException(status_code=503, detail="MCP server not connected")
    except json.JSONDecodeError:
        return {"status": "pending"}
    except Exception as e:
        logger.error("status check failed: %s", e)
        return {"status": "error", "message": str(e)}


@router.post("/logout")
async def do_logout():
    """Clear the authenticated session."""
    try:
        result = await mcp_bridge.call_tool("logout", {})
        set_auth_state(authenticated=False, profile=None)
        return json.loads(result)
    except RuntimeError:
        raise HTTPException(status_code=503, detail="MCP server not connected")
    except Exception as e:
        logger.error("logout failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
