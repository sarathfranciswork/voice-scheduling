"""Realtime voice agent endpoints.

Provides ephemeral key generation for WebRTC sessions, a tool-call proxy
for voice agent function calling, and transcript persistence.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import database as db
from app import mcp_bridge
from app.config import OPENAI_API_KEY, get_auth_state

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

VOICE_TOOLS_EXCLUDE = {
    "login_to_cvs",
    "verify_otp",
    "verify_dob",
    "start_manual_login",
    "check_login_status",
    "logout",
    "refresh_session",
}


def _get_voice_tool_schemas() -> list[dict[str, Any]]:
    """Return MCP tool definitions filtered for voice mode.

    Excludes auth/login tools (security risk in voice -- passwords, OTP codes)
    and internal tools not useful for conversational interaction.
    """
    all_tools = mcp_bridge.get_openai_tools()
    return [
        t for t in all_tools
        if t["function"]["name"] not in VOICE_TOOLS_EXCLUDE
    ]


def _build_voice_system_prompt() -> str:
    """Build the voice-optimized system prompt with dynamic auth context."""
    from app.config import VOICE_SYSTEM_PROMPT

    prompt = VOICE_SYSTEM_PROMPT
    auth = get_auth_state()

    if auth["authenticated"]:
        profile = auth.get("profile") or {}
        first = profile.get("firstName", "")
        last = profile.get("lastName", "")
        dob = profile.get("dateOfBirth", "")
        email = profile.get("email", "")
        phone = profile.get("phone", "")
        gender = profile.get("gender", "")
        address = profile.get("address") or {}

        auth_block = (
            "\n\n== CURRENT SESSION STATE ==\n"
            "The user is ALREADY LOGGED IN to their CVS account. "
            "Do NOT ask them to log in. Do NOT mention login. "
            "They are fully authenticated.\n"
        )
        if first or last:
            auth_block += f"User name: {first} {last}\n"
        if email:
            auth_block += f"User email: {email}\n"
        if dob:
            auth_block += f"User DOB: {dob}\n"
        if phone:
            auth_block += f"User phone: {phone}\n"
        if gender:
            auth_block += f"User gender: {gender}\n"
        if address.get("street"):
            addr_str = (
                f"{address['street']}, {address.get('city', '')}, "
                f"{address.get('state', '')} {address.get('zip', '')}"
            )
            auth_block += f"User address: {addr_str}\n"

        auth_block += (
            "\nGreet the user by first name. When scheduling, use their cached "
            "details -- do NOT ask again for name, email, DOB, phone, address, "
            "or gender. Just confirm: 'I have your details on file, shall I proceed?'\n"
        )
        prompt += auth_block

    return prompt


@router.get("/token")
async def get_realtime_token():
    """Generate an ephemeral client key for a WebRTC voice session.

    Returns the key, voice-optimized instructions, voice setting,
    and filtered tool schemas so the frontend can configure the
    RealtimeAgent and RealtimeSession.
    """
    if not OPENAI_API_KEY:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")

    instructions = _build_voice_system_prompt()
    tools = _get_voice_tool_schemas()

    try:
        async with httpx.AsyncClient(timeout=15) as http:
            resp = await http.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "session": {
                        "type": "realtime",
                        "model": "gpt-realtime",
                    }
                },
            )
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        logger.error("Failed to create ephemeral key: %s %s", e.response.status_code, e.response.text[:500])
        raise HTTPException(status_code=502, detail="Failed to create voice session with OpenAI")
    except httpx.RequestError as e:
        logger.error("Network error creating ephemeral key: %s", e)
        raise HTTPException(status_code=502, detail="Network error contacting OpenAI")

    data = resp.json()
    ephemeral_key = data.get("client_secret", {}).get("value") or data.get("value")
    if not ephemeral_key:
        logger.error("Unexpected response from client_secrets: %s", json.dumps(data)[:500])
        raise HTTPException(status_code=502, detail="No ephemeral key in OpenAI response")

    return {
        "key": ephemeral_key,
        "instructions": instructions,
        "voice": "coral",
        "tools": tools,
    }


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any] = {}


@router.post("/tool-call")
async def execute_tool_call(req: ToolCallRequest):
    """Execute an MCP tool on behalf of the voice agent.

    The voice agent's tool() execute functions in the browser call this
    endpoint, which proxies to the MCP server via mcp_bridge.
    """
    try:
        result = await mcp_bridge.call_tool(req.name, req.arguments)
        return {"result": result}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("Voice tool-call %s failed: %s", req.name, e)
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {e}")


class TranscriptMessage(BaseModel):
    role: str
    content: str


class SaveTranscriptRequest(BaseModel):
    messages: list[TranscriptMessage]


@router.post("/conversations/{conversation_id}/messages")
async def save_transcript(conversation_id: str, req: SaveTranscriptRequest):
    """Persist voice transcript entries to the conversation database.

    Called by the frontend when a voice session ends so that
    voice messages appear in the chat history.
    """
    conv = await db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    saved = []
    for entry in req.messages:
        msg = await db.add_message(
            conversation_id,
            role=entry.role,
            content=entry.content,
        )
        saved.append(msg)

    return {"saved": len(saved)}
