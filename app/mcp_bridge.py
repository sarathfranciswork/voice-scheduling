"""
Bridge between the Python API layer and the MCP server.

Connects to the MCP server via fastmcp.Client, discovers available tools,
converts their schemas to OpenAI function-calling format, and executes tool calls.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import Client as MCPClient

from app.config import MCP_SERVER_URL, set_auth_state

logger = logging.getLogger(__name__)

# The first MCP tool call bootstraps a Playwright browser session (~30-45s),
# so we need a generous timeout for the client.
MCP_TOOL_TIMEOUT_SECONDS = 120

_client: MCPClient | None = None
_openai_tools: list[dict[str, Any]] = []
_tool_map: dict[str, dict[str, Any]] = {}


async def connect() -> None:
    """Connect to the MCP server and cache tool definitions."""
    global _client, _openai_tools, _tool_map

    logger.info(f"Connecting to MCP server at {MCP_SERVER_URL}")
    _client = MCPClient(MCP_SERVER_URL, timeout=MCP_TOOL_TIMEOUT_SECONDS)

    async with _client:
        tools = await _client.list_tools()

    _openai_tools = []
    _tool_map = {}

    for tool in tools:
        openai_func = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
            },
        }
        _openai_tools.append(openai_func)
        _tool_map[tool.name] = {"mcp_tool": tool, "openai_def": openai_func}

    logger.info(f"Discovered {len(_openai_tools)} MCP tools: {[t['function']['name'] for t in _openai_tools]}")


async def disconnect() -> None:
    global _client
    _client = None


def get_openai_tools() -> list[dict[str, Any]]:
    """Return tool definitions in OpenAI function-calling format."""
    return _openai_tools


TOOL_DISPLAY_NAMES: dict[str, str] = {
    "get_eligible_vaccines": "Checking vaccine eligibility...",
    "check_vaccine_eligibility": "Verifying eligibility details...",
    "search_stores": "Searching nearby CVS pharmacies...",
    "get_available_time_slots": "Finding available time slots...",
    "get_store_details": "Loading store information...",
    "soft_reserve_slot": "Reserving your time slot...",
    "submit_patient_details": "Saving patient information...",
    "get_questionnaire": "Loading health screening questions...",
    "submit_questionnaire": "Submitting questionnaire...",
    "get_user_schedule": "Checking existing appointments...",
    "confirm_appointment": "Confirming your appointment...",
    "address_typeahead": "Looking up address...",
    "refresh_session": "Refreshing CVS session...",
    "login_to_cvs": "Logging in to CVS...",
    "verify_otp": "Verifying code...",
    "verify_dob": "Verifying date of birth...",
    "get_patient_profile": "Loading your profile...",
    "get_my_appointments": "Fetching your appointments...",
    "cancel_appointment": "Cancelling appointment...",
    "start_manual_login": "Opening CVS login...",
    "check_login_status": "Checking login status...",
    "logout": "Signing out...",
}


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool on the MCP server and return the result as a string."""
    if _client is None:
        raise RuntimeError("MCP bridge not connected. Call connect() first.")

    logger.info(f"Calling MCP tool: {name} with args: {json.dumps(arguments, default=str)[:200]}")

    async with _client:
        result = await _client.call_tool(name, arguments)

    text_parts = []
    for content_block in result.content:
        if hasattr(content_block, "text"):
            text_parts.append(content_block.text)

    output = "\n".join(text_parts) if text_parts else str(result.data)
    logger.info(f"Tool {name} result length: {len(output)} chars")

    _sync_auth_state(name, output)
    return output


_AUTH_TOOLS = {"login_to_cvs", "verify_otp", "verify_dob", "check_login_status"}


def _sync_auth_state(tool_name: str, result: str) -> None:
    """Update shared auth state when auth-related tools complete."""
    if tool_name in _AUTH_TOOLS:
        try:
            data = json.loads(result)
            if data.get("status") == "authenticated":
                set_auth_state(authenticated=True, profile=data.get("profile"))
        except (json.JSONDecodeError, TypeError):
            pass
    elif tool_name == "logout":
        set_auth_state(authenticated=False, profile=None)
