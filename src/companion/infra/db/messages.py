"""
companion/infra/db/messages.py — ``messages`` table.

Public API:
  create_message — insert user/assistant/system row (validates role and non-empty content)
  get_messages_by_session — last N messages for a session, chronological order

Internal: (none)
"""
from __future__ import annotations

from typing import Literal, Optional

import psycopg
from psycopg.errors import ForeignKeyViolation

from .internal import _exec_returning_id, _fetch_all_rows

Role = Literal["user", "assistant", "system"]
_ALLOWED_ROLES = {"user", "assistant", "system"}


def create_message(
    user_id: int,
    session_id: int,
    role: Role,
    content: str,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    user_id = int(user_id)
    session_id = int(session_id)

    role = str(role).strip()
    if role not in _ALLOWED_ROLES:
        raise ValueError(f"invalid role: {role}")

    content = str(content)
    if not content.strip():
        raise ValueError("content must be non-empty")

    sql = """
    INSERT INTO messages (user_id, session_id, role, content)
    VALUES (%(user_id)s, %(session_id)s, %(role)s, %(content)s)
    RETURNING id;
    """
    try:
        return _exec_returning_id(
            sql,
            {
                "user_id": user_id,
                "session_id": session_id,
                "role": role,
                "content": content,
            },
            conn=conn,
        )
    except ForeignKeyViolation:
        raise ValueError(f"user_id={user_id} or session_id={session_id} not found")


def get_messages_by_session(
    session_id: int,
    limit: int,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    session_id = int(session_id)
    limit = int(limit)
    if limit <= 0:
        return []

    sql = """
    SELECT id, user_id, session_id, role, content, created_at
    FROM (
        SELECT id, user_id, session_id, role, content, created_at
        FROM messages
        WHERE session_id = %(session_id)s
        ORDER BY created_at DESC
        LIMIT %(limit)s
    ) t
    ORDER BY created_at ASC;
    """
    rows = _fetch_all_rows(sql, {"session_id": session_id, "limit": limit}, conn=conn)
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "session_id": r[2],
            "role": r[3],
            "content": r[4],
            "created_at": r[5],
        }
        for r in rows
    ]
