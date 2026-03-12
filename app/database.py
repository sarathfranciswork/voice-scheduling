"""SQLite database for conversation history persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from app.config import DATABASE_PATH

_db: aiosqlite.Connection | None = None


async def init_db() -> None:
    """Create tables if they don't exist and open the connection."""
    global _db
    db_path = Path(DATABASE_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _db = await aiosqlite.connect(str(db_path))
    _db.row_factory = aiosqlite.Row

    await _db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New Conversation',
            theme TEXT NOT NULL DEFAULT 'red',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            tool_name TEXT,
            tool_call_id TEXT,
            tool_args TEXT,
            tool_result TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages(conversation_id, created_at);
    """)
    await _db.commit()


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Conversations ──────────────────────────────────────────────────────────


async def create_conversation(title: str = "New Conversation", theme: str = "red") -> dict[str, Any]:
    assert _db is not None
    cid = str(uuid.uuid4())
    now = _now()
    await _db.execute(
        "INSERT INTO conversations (id, title, theme, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (cid, title, theme, now, now),
    )
    await _db.commit()
    return {"id": cid, "title": title, "theme": theme, "created_at": now, "updated_at": now}


async def list_conversations() -> list[dict[str, Any]]:
    assert _db is not None
    cursor = await _db.execute(
        "SELECT id, title, theme, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    assert _db is not None
    cursor = await _db.execute(
        "SELECT id, title, theme, created_at, updated_at FROM conversations WHERE id = ?",
        (conversation_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def update_conversation(conversation_id: str, **kwargs: Any) -> dict[str, Any] | None:
    assert _db is not None
    allowed = {"title", "theme"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return await get_conversation(conversation_id)

    updates["updated_at"] = _now()
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [conversation_id]

    await _db.execute(f"UPDATE conversations SET {set_clause} WHERE id = ?", values)
    await _db.commit()
    return await get_conversation(conversation_id)


async def delete_conversation(conversation_id: str) -> bool:
    assert _db is not None
    await _db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
    cursor = await _db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    await _db.commit()
    return cursor.rowcount > 0


# ── Messages ───────────────────────────────────────────────────────────────


async def add_message(
    conversation_id: str,
    role: str,
    content: str = "",
    tool_name: str | None = None,
    tool_call_id: str | None = None,
    tool_args: dict | None = None,
    tool_result: str | None = None,
) -> dict[str, Any]:
    assert _db is not None
    mid = str(uuid.uuid4())
    now = _now()
    await _db.execute(
        """INSERT INTO messages
           (id, conversation_id, role, content, tool_name, tool_call_id, tool_args, tool_result, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            mid,
            conversation_id,
            role,
            content,
            tool_name,
            tool_call_id,
            json.dumps(tool_args) if tool_args else None,
            tool_result,
            now,
        ),
    )
    await _db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id)
    )
    await _db.commit()
    return {
        "id": mid,
        "conversation_id": conversation_id,
        "role": role,
        "content": content,
        "tool_name": tool_name,
        "tool_call_id": tool_call_id,
        "tool_args": tool_args,
        "tool_result": tool_result,
        "created_at": now,
    }


async def get_messages(conversation_id: str) -> list[dict[str, Any]]:
    assert _db is not None
    cursor = await _db.execute(
        """SELECT id, conversation_id, role, content, tool_name, tool_call_id, tool_args, tool_result, created_at
           FROM messages WHERE conversation_id = ? ORDER BY created_at ASC""",
        (conversation_id,),
    )
    rows = await cursor.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if d.get("tool_args") and isinstance(d["tool_args"], str):
            try:
                d["tool_args"] = json.loads(d["tool_args"])
            except json.JSONDecodeError:
                pass
        result.append(d)
    return result


async def auto_title_conversation(conversation_id: str, first_user_message: str) -> None:
    """Set conversation title from the first user message (truncated)."""
    title = first_user_message.strip()[:80]
    if len(first_user_message.strip()) > 80:
        title += "..."
    await update_conversation(conversation_id, title=title)
