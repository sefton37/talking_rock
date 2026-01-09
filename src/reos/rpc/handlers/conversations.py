"""Conversation handlers.

Manages chat conversations - creation, listing, message retrieval.
"""

from __future__ import annotations

import uuid
from typing import Any

from reos.db import Database
from reos.rpc.router import register


@register("conversation/start", needs_db=True)
def handle_start(db: Database, *, title: str | None = None) -> dict[str, Any]:
    """Start a new conversation."""
    conversation_id = uuid.uuid4().hex[:12]
    db.create_conversation(conversation_id=conversation_id, title=title)
    return {"conversation_id": conversation_id}


@register("conversation/list", needs_db=True)
def handle_list(db: Database, *, limit: int = 50) -> dict[str, Any]:
    """List recent conversations."""
    conversations = db.iter_conversations(limit=limit)
    return {
        "conversations": [
            {
                "id": str(c.get("id")),
                "title": c.get("title"),
                "started_at": c.get("started_at"),
                "last_active_at": c.get("last_active_at"),
            }
            for c in conversations
        ]
    }


@register("conversation/get_messages", needs_db=True)
def handle_get_messages(
    db: Database,
    *,
    conversation_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Get messages for a conversation."""
    messages = db.get_messages(conversation_id=conversation_id, limit=limit)
    return {
        "messages": [
            {
                "id": str(m.get("id")),
                "role": m.get("role"),
                "content": m.get("content"),
                "message_type": m.get("message_type"),
                "metadata": m.get("metadata"),
                "created_at": m.get("created_at"),
            }
            for m in messages
        ]
    }
