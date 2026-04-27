"""
User account, profile, and display-name service operations.
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


def effective_form_of_address(
    explicit: str | None,
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> str:
    """
    Text the model should use to address the user: per-bot form_of_address if set,
    otherwise the user's profile display_name (nickname). Empty explicit falls through to display_name.
    """
    s = (explicit or "").strip()
    if s:
        return s
    return (db.get_display_name(user_id, conn=conn) or "").strip()


def get_display_name(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> str | None:
    return db.get_display_name(user_id, conn=conn)


def get_me(user_id: int, conn: Optional[psycopg.Connection] = None) -> dict:
    display_name = db.get_display_name(user_id, conn=conn) or ""
    avatar = db.get_user_avatar_data_url(user_id, conn=conn)
    return {"display_name": display_name, "avatar_data_url": avatar}


def update_me(
    user_id: int,
    *,
    display_name: str | None = None,
    avatar_data_url: str | None = None,
    update_display_name: bool = False,
    update_avatar: bool = False,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    if update_display_name:
        assert display_name is not None
        db.update_user_display_name(user_id, display_name, conn=conn)
    if update_avatar:
        db.update_user_avatar_data_url(user_id, avatar_data_url, conn=conn)
    return get_me(user_id, conn=conn)
