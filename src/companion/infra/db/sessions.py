"""
companion/infra/db/sessions.py — ``sessions`` table (legacy per-user session; bots use their own session_id).

Public API:
  create_session — insert new open session row
  get_active_session_id — latest non-ended session for user, if any
  get_or_create_session — reuse active or insert new
  get_session_time — (started_at, ended_at) for a session id
  end_session — set ended_at=now() if still open; returns whether a row was updated

Internal: (none)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import psycopg

from .internal import _exec_and_rowcount, _exec_returning_id, _fetch_one_row, _fetch_one_value


def create_session(user_id: int, conn: Optional[psycopg.Connection] = None) -> int:
    """Create a new session for the user. Used when creating a new bot (one bot = one session)."""
    user_id = int(user_id)
    sql = "INSERT INTO sessions (user_id) VALUES (%(user_id)s) RETURNING id;"
    return _exec_returning_id(sql, {"user_id": user_id}, conn=conn)


def get_active_session_id(user_id, conn: Optional[psycopg.Connection] = None) -> Optional[int]:
    user_id = int(user_id)
    sql = """
        SELECT id
        FROM sessions
        WHERE user_id = %(user_id)s AND ended_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1;
        """
    return _fetch_one_value(sql, {"user_id": user_id}, conn=conn)


def get_or_create_session(user_id: int, conn: Optional[psycopg.Connection] = None) -> int:
    user_id = int(user_id)
    sid = get_active_session_id(user_id, conn=conn)
    if sid is not None:
        return sid
    sql = "INSERT INTO sessions (user_id) VALUES (%(user_id)s) RETURNING id;"
    return _exec_returning_id(sql, {"user_id": user_id}, conn=conn)


def get_session_time(
    session_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> tuple[datetime, Optional[datetime]]:
    session_id = int(session_id)
    sql = "SELECT started_at, ended_at FROM sessions WHERE id = %(session_id)s;"
    row = _fetch_one_row(sql, {"session_id": session_id}, conn=conn)
    if row is None:
        raise ValueError(f"session_id={session_id} not found")
    return row[0], row[1]


def end_session(session_id: int, conn: Optional[psycopg.Connection] = None) -> bool:
    session_id = int(session_id)
    sql = "UPDATE sessions SET ended_at = now() WHERE id = %(session_id)s AND ended_at IS NULL;"
    rowcount = _exec_and_rowcount(sql, {"session_id": session_id}, conn=conn)
    return rowcount > 0
