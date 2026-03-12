"""WebSocket endpoint for real-time chat streaming."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import database as db
from app.chat_agent import stream_response

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat/{conversation_id}")
async def chat_websocket(websocket: WebSocket, conversation_id: str):
    """
    WebSocket chat endpoint.

    Client sends: {"type": "user_message", "content": "..."}
    Server sends: {"type": "chunk"|"tool_start"|"tool_result"|"done"|"error", ...}
    """
    await websocket.accept()

    # Verify conversation exists, or create it
    conv = await db.get_conversation(conversation_id)
    if not conv:
        conv = await db.create_conversation()
        await websocket.send_json({"type": "conversation_created", "conversation": conv})

    logger.info(f"WebSocket connected for conversation {conversation_id}")

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "user_message":
                content = msg.get("content", "").strip()
                if not content:
                    await websocket.send_json({"type": "error", "message": "Empty message"})
                    continue

                async for event in stream_response(conversation_id, content):
                    await websocket.send_json(event)

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            else:
                await websocket.send_json({"type": "error", "message": f"Unknown type: {msg_type}"})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for conversation {conversation_id}")
    except Exception:
        logger.exception(f"WebSocket error for conversation {conversation_id}")
        try:
            await websocket.send_json({"type": "error", "message": "Internal server error"})
        except Exception:
            pass
