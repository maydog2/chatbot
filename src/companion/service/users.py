"""
companion/service/users.py — user registration and password verification.

Public API:
  register_user — create user row (per-bot relationship rows created when they add a bot)
  login — verify username/password, return user_id or raise ValueError
"""
from __future__ import annotations

from typing import Optional

import psycopg

from companion.infra import db


def register_user(
    display_name: str,
    username: str,
    password: str,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    """
    Business action: create a new user. Per-bot relationship rows are created when they add a bot.
    Transaction boundary should be managed by caller (e.g., FastAPI request scope).
    """
    return db.create_user(display_name, username, password, conn=conn)


def login(
    username: str,
    password: str,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    """Business action: verify username/password and return user_id if valid."""
    user_id = db.get_user_id(username, conn=conn)
    if user_id is None:
        raise ValueError("invalid username or password")

    if not db.verify_password(user_id, password, conn=conn):
        raise ValueError("invalid username or password")

    return user_id
