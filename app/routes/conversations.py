"""REST endpoints for conversation CRUD and message history."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import database as db

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    title: str = "New Conversation"
    theme: str = "red"


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    theme: str | None = None


@router.get("")
async def list_conversations():
    return await db.list_conversations()


@router.post("", status_code=201)
async def create_conversation(req: CreateConversationRequest):
    return await db.create_conversation(title=req.title, theme=req.theme)


@router.get("/{conversation_id}")
async def get_conversation(conversation_id: str):
    conv = await db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await db.get_messages(conversation_id)
    return {**conv, "messages": messages}


@router.patch("/{conversation_id}")
async def update_conversation(conversation_id: str, req: UpdateConversationRequest):
    conv = await db.update_conversation(conversation_id, title=req.title, theme=req.theme)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: str):
    deleted = await db.delete_conversation(conversation_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
