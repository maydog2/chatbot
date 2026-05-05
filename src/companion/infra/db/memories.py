"""
companion/infra/db/memories.py — ``memories`` table helpers.
"""
from __future__ import annotations

import math
from typing import Optional

import psycopg
from psycopg.errors import ForeignKeyViolation

from .internal import _exec_and_rowcount, _exec_returning_id, _fetch_all_rows

MemoryType = str
_ALLOWED_MEMORY_TYPES = {"preference", "goal", "background", "instruction"}


def _validate_memory_type(memory_type: str) -> str:
    memory_type = str(memory_type).strip()
    if memory_type not in _ALLOWED_MEMORY_TYPES:
        raise ValueError(f"invalid memory_type: {memory_type}")
    return memory_type


def _embedding_literal(embedding: list[float] | tuple[float, ...] | None) -> str | None:
    if embedding is None:
        return None
    values: list[str] = []
    for value in embedding:
        f = float(value)
        if not math.isfinite(f):
            raise ValueError("embedding must contain only finite numbers")
        values.append(format(f, ".9g"))
    if not values:
        return None
    return "[" + ",".join(values) + "]"


def create_memory(
    user_id: int,
    session_id: int,
    source_message_id: int | None,
    content: str,
    memory_type: MemoryType,
    *,
    importance: int = 50,
    embedding: list[float] | tuple[float, ...] | None = None,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    user_id = int(user_id)
    session_id = int(session_id)
    source_message_id = None if source_message_id is None else int(source_message_id)
    content = str(content).strip()
    if not content:
        raise ValueError("content must be non-empty")
    memory_type = _validate_memory_type(memory_type)
    importance = int(importance)
    if importance < 0 or importance > 100:
        raise ValueError("importance must be between 0 and 100")

    sql = """
    INSERT INTO memories (
        user_id, session_id, source_message_id, content, memory_type, importance, embedding
    )
    VALUES (
        %(user_id)s, %(session_id)s, %(source_message_id)s, %(content)s,
        %(memory_type)s, %(importance)s, %(embedding)s::vector
    )
    RETURNING id;
    """
    try:
        return _exec_returning_id(
            sql,
            {
                "user_id": user_id,
                "session_id": session_id,
                "source_message_id": source_message_id,
                "content": content,
                "memory_type": memory_type,
                "importance": importance,
                "embedding": _embedding_literal(embedding),
            },
            conn=conn,
        )
    except ForeignKeyViolation:
        raise ValueError("user_id, session_id, or source_message_id not found")


def update_memory(
    memory_id: int,
    *,
    content: str | None = None,
    memory_type: MemoryType | None = None,
    importance: int | None = None,
    source_message_id: int | None = None,
    embedding: list[float] | tuple[float, ...] | None = None,
    is_active: bool | None = None,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    memory_id = int(memory_id)
    content = None if content is None else str(content).strip()
    if content == "":
        raise ValueError("content must be non-empty")
    if memory_type is not None:
        memory_type = _validate_memory_type(memory_type)
    if importance is not None:
        importance = int(importance)
        if importance < 0 or importance > 100:
            raise ValueError("importance must be between 0 and 100")

    sql = """
    UPDATE memories
    SET content = COALESCE(%(content)s, content),
        memory_type = COALESCE(%(memory_type)s, memory_type),
        importance = COALESCE(%(importance)s, importance),
        source_message_id = COALESCE(%(source_message_id)s, source_message_id),
        embedding = COALESCE(%(embedding)s::vector, embedding),
        is_active = COALESCE(%(is_active)s, is_active)
    WHERE id = %(memory_id)s;
    """
    return (
        _exec_and_rowcount(
            sql,
            {
                "memory_id": memory_id,
                "content": content,
                "memory_type": memory_type,
                "importance": importance,
                "source_message_id": source_message_id,
                "embedding": _embedding_literal(embedding),
                "is_active": is_active,
            },
            conn=conn,
        )
        > 0
    )


def deactivate_memory(
    memory_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    return update_memory(int(memory_id), is_active=False, conn=conn)


def enforce_memory_limits(
    user_id: int,
    *,
    active_limit: int = 100,
    total_limit: int = 1000,
    conn: Optional[psycopg.Connection] = None,
) -> dict[str, int]:
    """Cap one user's active and total memory rows.

    Active rows beyond ``active_limit`` are marked inactive, keeping higher importance and
    more recently updated rows. Total rows beyond ``total_limit`` are deleted with active
    rows prioritized for retention.
    """
    user_id = int(user_id)
    active_limit = max(0, int(active_limit))
    total_limit = max(0, int(total_limit))

    deactivate_sql = """
    WITH extra AS (
        SELECT id
        FROM memories
        WHERE user_id = %(user_id)s
          AND is_active = true
        ORDER BY importance DESC, updated_at DESC, id DESC
        OFFSET %(active_limit)s
    )
    UPDATE memories
    SET is_active = false
    WHERE id IN (SELECT id FROM extra);
    """
    delete_sql = """
    WITH extra AS (
        SELECT id
        FROM memories
        WHERE user_id = %(user_id)s
        ORDER BY is_active DESC, importance DESC, updated_at DESC, id DESC
        OFFSET %(total_limit)s
    )
    DELETE FROM memories
    WHERE id IN (SELECT id FROM extra);
    """
    params = {"user_id": user_id, "active_limit": active_limit, "total_limit": total_limit}
    deactivated = _exec_and_rowcount(deactivate_sql, params, conn=conn)
    deleted = _exec_and_rowcount(delete_sql, params, conn=conn)
    return {"deactivated": deactivated, "deleted": deleted}


def list_active_memories(
    user_id: int,
    *,
    limit: int = 20,
    memory_type: MemoryType | None = None,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    user_id = int(user_id)
    limit = int(limit)
    if limit <= 0:
        return []
    if memory_type is not None:
        memory_type = _validate_memory_type(memory_type)
    if memory_type is None:
        sql = """
        SELECT id, user_id, session_id, source_message_id, content, memory_type,
               importance, created_at, updated_at, is_active, embedding::text
        FROM memories
        WHERE user_id = %(user_id)s
          AND is_active = true
        ORDER BY importance DESC, updated_at DESC
        LIMIT %(limit)s;
        """
        params = {"user_id": user_id, "limit": limit}
    else:
        sql = """
        SELECT id, user_id, session_id, source_message_id, content, memory_type,
               importance, created_at, updated_at, is_active, embedding::text
        FROM memories
        WHERE user_id = %(user_id)s
          AND is_active = true
          AND memory_type = %(memory_type)s
        ORDER BY importance DESC, updated_at DESC
        LIMIT %(limit)s;
        """
        params = {"user_id": user_id, "memory_type": memory_type, "limit": limit}
    rows = _fetch_all_rows(sql, params, conn=conn)
    return [_row_to_memory(r) for r in rows]


def find_active_memories_for_dedupe(
    user_id: int,
    *,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    user_id = int(user_id)
    sql = """
    SELECT id, user_id, session_id, source_message_id, content, memory_type,
           importance, created_at, updated_at, is_active, embedding::text
    FROM memories
    WHERE user_id = %(user_id)s
      AND is_active = true
    ORDER BY updated_at DESC;
    """
    rows = _fetch_all_rows(sql, {"user_id": user_id}, conn=conn)
    return [_row_to_memory(r) for r in rows]


def list_active_memories_for_retrieval(
    user_id: int,
    *,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    user_id = int(user_id)
    sql = """
    SELECT id, user_id, session_id, source_message_id, content, memory_type,
           importance, created_at, updated_at, is_active, embedding::text
    FROM memories
    WHERE user_id = %(user_id)s
      AND is_active = true
    ORDER BY importance DESC, updated_at DESC, id DESC;
    """
    rows = _fetch_all_rows(sql, {"user_id": user_id}, conn=conn)
    return [_row_to_memory(r) for r in rows]


def search_active_memories_by_embedding(
    user_id: int,
    embedding: list[float] | tuple[float, ...],
    *,
    limit: int = 8,
    memory_type: MemoryType | None = None,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    user_id = int(user_id)
    limit = int(limit)
    if limit <= 0:
        return []
    if memory_type is not None:
        memory_type = _validate_memory_type(memory_type)
    embedding_literal = _embedding_literal(embedding)
    if embedding_literal is None:
        return []

    memory_type_filter = ""
    params: dict[str, object] = {
        "user_id": user_id,
        "embedding": embedding_literal,
        "limit": limit,
    }
    if memory_type is not None:
        memory_type_filter = "AND memory_type = %(memory_type)s"
        params["memory_type"] = memory_type

    sql = f"""
    SELECT id, user_id, session_id, source_message_id, content, memory_type,
           importance, created_at, updated_at, is_active,
           embedding <=> %(embedding)s::vector AS distance
    FROM memories
    WHERE user_id = %(user_id)s
      AND is_active = true
      AND embedding IS NOT NULL
      {memory_type_filter}
    ORDER BY embedding <=> %(embedding)s::vector,
             importance DESC,
             updated_at DESC,
             id DESC
    LIMIT %(limit)s;
    """
    try:
        rows = _fetch_all_rows(sql, params, conn=conn)
    except psycopg.Error:
        logger.debug("search_active_memories_by_embedding failed", exc_info=True)
        return []
        
    memories = []
    for row in rows:
        (
            memory_id,
            row_user_id,
            session_id,
            source_message_id,
            content,
            row_memory_type,
            importance,
            created_at,
            updated_at,
            is_active,
            distance,
        ) = row
        memories.append(
            {
                "id": memory_id,
                "user_id": row_user_id,
                "session_id": session_id,
                "source_message_id": source_message_id,
                "content": content,
                "memory_type": row_memory_type,
                "importance": importance,
                "created_at": created_at,
                "updated_at": updated_at,
                "is_active": is_active,
                "distance": float(distance) if distance is not None else None,
            }
        )
    return memories


def _row_to_memory(row: tuple) -> dict:
    return {
        "id": row[0],
        "user_id": row[1],
        "session_id": row[2],
        "source_message_id": row[3],
        "content": row[4],
        "memory_type": row[5],
        "importance": row[6],
        "created_at": row[7],
        "updated_at": row[8],
        "is_active": row[9],
        "embedding": row[10],
    }
