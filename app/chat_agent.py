"""
Chat agent that orchestrates OpenAI Chat Completions with MCP tool calling.

Streams responses token-by-token and handles the tool-call loop:
1. Send messages + tools to GPT-4o with streaming
2. If response contains tool_calls, execute each via MCP bridge
3. Append tool results and re-call GPT-4o
4. Repeat until we get a text response
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

from openai import AsyncOpenAI

from app import database as db
from app import mcp_bridge
from app.config import OPENAI_API_KEY, OPENAI_MODEL, SYSTEM_PROMPT, get_auth_state

logger = logging.getLogger(__name__)

_openai: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai
    if _openai is None:
        _openai = AsyncOpenAI(api_key=OPENAI_API_KEY)
    return _openai


def _build_system_prompt() -> str:
    """Build system prompt with dynamic auth context."""
    auth = get_auth_state()
    prompt = SYSTEM_PROMPT

    if auth["authenticated"]:
        profile = auth.get("profile") or {}
        first = profile.get("firstName", "")
        last = profile.get("lastName", "")
        dob = profile.get("dateOfBirth", "")
        email = profile.get("email", "")
        phone = profile.get("phone", "")
        gender = profile.get("gender", "")
        address = profile.get("address") or {}

        auth_note = (
            "\n\n== CURRENT SESSION STATE ==\n"
            "The user is ALREADY LOGGED IN to their CVS account (via the Login button in the header). "
            "Do NOT ask them to log in, do NOT mention login methods (OTP/password), and do NOT call "
            "login_to_cvs, verify_otp, or verify_dob. They are already authenticated.\n"
        )
        if first or last:
            full_name = f"{first} {last}".strip()
            auth_note += f"User name: {full_name}\n"
        if email:
            auth_note += f"User email: {email}\n"
        if dob:
            auth_note += f"User DOB (cached): {dob}\n"
        if phone:
            auth_note += f"User phone: {phone}\n"
        if gender:
            auth_note += f"User gender: {gender}\n"
        if address.get("street"):
            auth_note += (
                f"User address: {address['street']}, {address.get('city', '')}, "
                f"{address.get('state', '')} {address.get('zip', '')}\n"
            )
        auth_note += (
            "\nGreet the user by their first name for a personalized experience. "
            "You can directly call get_patient_profile, get_my_appointments, cancel_appointment, "
            "and proceed with scheduling using their cached profile data.\n\n"
            "IMPORTANT: When scheduling, you have ALL their details above. "
            "Do NOT ask the user again for name, email, DOB, phone, address, or gender. "
            "Use the cached values above to call submit_patient_details directly. "
            "Simply confirm: 'I have your details on file — shall I proceed with booking?' "
            "If they want to schedule, skip asking for DOB (it is already cached) and proceed "
            "directly to vaccine selection and store search."
        )
        prompt += auth_note

    return prompt


def _build_openai_messages(db_messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert database message rows to OpenAI Chat Completions message format."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": _build_system_prompt()}]

    for msg in db_messages:
        role = msg["role"]

        if role == "user":
            messages.append({"role": "user", "content": msg["content"]})
        elif role == "assistant":
            messages.append({"role": "assistant", "content": msg["content"]})
        elif role == "tool_call":
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": msg.get("tool_call_id", "call_0"),
                    "type": "function",
                    "function": {
                        "name": msg.get("tool_name", ""),
                        "arguments": json.dumps(msg.get("tool_args", {})),
                    },
                }],
            })
        elif role == "tool_result":
            messages.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", "call_0"),
                "content": msg.get("tool_result", ""),
            })

    return messages


# Event types yielded during streaming
# {"type": "chunk", "content": "partial text"}
# {"type": "tool_start", "name": "search_stores", "display": "Searching..."}
# {"type": "tool_result", "name": "search_stores", "summary": "Found 5 stores"}
# {"type": "done", "message_id": "...", "full_content": "..."}
# {"type": "error", "message": "..."}

StreamEvent = dict[str, Any]

MAX_TOOL_ROUNDS = 8


async def stream_response(
    conversation_id: str,
    user_message: str,
) -> AsyncGenerator[StreamEvent, None]:
    """
    Process a user message and stream the assistant response.

    Yields StreamEvent dicts that the WebSocket handler sends to the client.
    """
    client = _get_openai()
    tools = mcp_bridge.get_openai_tools()

    # Save user message
    await db.add_message(conversation_id, "user", user_message)

    # Auto-title on first message
    existing = await db.get_messages(conversation_id)
    user_msgs = [m for m in existing if m["role"] == "user"]
    if len(user_msgs) == 1:
        await db.auto_title_conversation(conversation_id, user_message)

    # Build message history for OpenAI
    all_messages = await db.get_messages(conversation_id)
    openai_messages = _build_openai_messages(all_messages)

    for _round in range(MAX_TOOL_ROUNDS):
        try:
            stream = await client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=openai_messages,
                tools=tools if tools else None,
                stream=True,
            )
        except Exception as e:
            logger.exception("OpenAI API error")
            yield {"type": "error", "message": f"OpenAI API error: {e}"}
            return

        full_content = ""
        tool_calls_acc: dict[int, dict[str, Any]] = {}
        finish_reason = None

        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Stream text content
            if delta.content:
                full_content += delta.content
                yield {"type": "chunk", "content": delta.content}

            # Accumulate tool calls
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc.id or "",
                            "name": "",
                            "arguments": "",
                        }
                    if tc.id:
                        tool_calls_acc[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_acc[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc.function.arguments

            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        # If we got text content (no tool calls), we're done
        if finish_reason != "tool_calls" or not tool_calls_acc:
            msg = await db.add_message(conversation_id, "assistant", full_content)
            yield {"type": "done", "message_id": msg["id"], "full_content": full_content}
            return

        # Handle tool calls
        assistant_tool_msg: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [],
        }

        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            assistant_tool_msg["tool_calls"].append({
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": tc["arguments"],
                },
            })

        openai_messages.append(assistant_tool_msg)

        # Execute each tool call
        for idx in sorted(tool_calls_acc.keys()):
            tc = tool_calls_acc[idx]
            tool_name = tc["name"]
            tool_call_id = tc["id"]

            try:
                tool_args = json.loads(tc["arguments"])
            except json.JSONDecodeError:
                tool_args = {}

            display = mcp_bridge.TOOL_DISPLAY_NAMES.get(tool_name, f"Running {tool_name}...")
            yield {"type": "tool_start", "name": tool_name, "display": display}

            # Save tool_call to DB
            await db.add_message(
                conversation_id, "tool_call",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_args=tool_args,
            )

            try:
                result = await mcp_bridge.call_tool(tool_name, tool_args)
            except Exception as e:
                logger.exception(f"Tool {tool_name} failed")
                result = f"Error executing {tool_name}: {e}"

            # Produce a short summary for the UI
            summary = _summarize_tool_result(tool_name, result)
            yield {"type": "tool_result", "name": tool_name, "summary": summary}

            # Save tool result to DB
            await db.add_message(
                conversation_id, "tool_result",
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                tool_result=result,
            )

            # Append to OpenAI messages for next round
            openai_messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": result,
            })

    # If we exhaust all rounds, yield what we have
    yield {"type": "error", "message": "Too many tool call rounds. Please try again."}


def _summarize_tool_result(tool_name: str, result: str) -> str:
    """Generate a short human-readable summary of a tool result for the UI."""
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return f"Completed {tool_name}"

    if tool_name == "search_stores":
        clinics = data.get("listOfClinics", [])
        return f"Found {len(clinics)} CVS location{'s' if len(clinics) != 1 else ''} nearby"
    elif tool_name == "get_available_time_slots":
        slots = data.get("availableTimeslotsResponse", [])
        return f"Found available time slots at {len(slots)} location{'s' if len(slots) != 1 else ''}"
    elif tool_name == "get_eligible_vaccines":
        vaccines = data.get("eligibleVaccineData", [])
        return f"Found {len(vaccines)} eligible vaccine{'s' if len(vaccines) != 1 else ''}"
    elif tool_name == "confirm_appointment":
        return "Appointment confirmed!"
    elif tool_name == "soft_reserve_slot":
        return "Time slot reserved"
    elif tool_name == "submit_patient_details":
        return "Patient details saved"

    return f"Completed {tool_name}"
