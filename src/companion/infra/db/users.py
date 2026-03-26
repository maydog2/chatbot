"""
companion/infra/db/users.py — ``users`` and ``auth_tokens`` tables.

Public API:
  Users: get_user_field, update_user_field, create_user, get_display_name, get_user_id,
    get_password_hash, get_created_at, get_user_avatar_data_url, verify_password,
    update_user_password, update_user_display_name, update_user_avatar_data_url, delete_user
  Tokens: create_auth_token, get_user_id_by_token_hash, revoke_token_by_hash

Notes:
  get_user_field / update_user_field are whitelisted column accessors; other modules rarely need them
  directly (service uses higher-level helpers). Token helpers use a direct DB_URL connection when
  conn is None so they work outside request-scoped transactions.

Internal: (none — all defs are intended for use via db package or tests)
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

import bcrypt
import psycopg
from psycopg.errors import UniqueViolation

from . import pool as _pool
from .internal import (
    _exec_and_rowcount,
    _exec_returning_id,
    _fetch_one_value,
)

UserField = Literal["id", "username", "display_name", "password_hash", "created_at"]

_ALLOWED_SELECT_FIELDS = frozenset(
    {"id", "username", "display_name", "avatar_data_url", "password_hash", "created_at"}
)
_ALLOWED_WHERE_FIELDS = frozenset({"id", "username"})
_ALLOWED_UPDATE_FIELDS = frozenset({"display_name", "avatar_data_url", "password_hash"})


def get_user_field(
    where_field: UserField,
    where_value: Any,
    select_field: UserField,
    conn: Optional[psycopg.Connection] = None,
) -> Optional[Any]:
    if where_field not in _ALLOWED_WHERE_FIELDS:
        raise ValueError(f"Invalid where_field: {where_field}")
    if select_field not in _ALLOWED_SELECT_FIELDS:
        raise ValueError(f"Invalid select_field: {select_field}")

    if where_field == "username":
        where_value = str(where_value).strip()
        if not where_value:
            return None

    if where_field == "id":
        where_value = int(where_value)

    sql = f"SELECT {select_field} FROM users WHERE {where_field} = %(v)s;"
    return _fetch_one_value(sql, {"v": where_value}, conn=conn)


def update_user_field(
    where_field: UserField,
    where_value: Any,
    update_field: UserField,
    update_value: Any,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    if where_field not in _ALLOWED_WHERE_FIELDS:
        raise ValueError(f"Invalid where_field: {where_field}")
    if update_field not in _ALLOWED_UPDATE_FIELDS:
        raise ValueError(f"Invalid update_field: {update_field}")

    if where_field == "username":
        where_value = str(where_value).strip()
        if not where_value:
            raise ValueError("username cannot be empty")

    if where_field == "id":
        where_value = int(where_value)

    if update_field == "display_name":
        update_value = str(update_value).strip()
        if not update_value:
            raise ValueError("display_name must be non-empty")

    sql = f"UPDATE users SET {update_field} = %(u)s WHERE {where_field} = %(w)s;"
    rowcount = _exec_and_rowcount(sql, {"u": update_value, "w": where_value}, conn=conn)
    return rowcount > 0


def create_user(display_name: str, username: str, password: str, conn: Optional[psycopg.Connection] = None) -> int:
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("display_name must be non-empty")

    username = username.strip()
    if not username:
        raise ValueError("username must be non-empty")

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    sql = """
    INSERT INTO users (display_name, username, password_hash)
    VALUES (%(display_name)s, %(username)s, %(password_hash)s)
    RETURNING id;
    """

    try:
        return _exec_returning_id(
            sql,
            {"display_name": display_name, "username": username, "password_hash": password_hash},
            conn=conn,
        )
    except UniqueViolation:
        raise ValueError(f"username already exists: {username}")


def get_display_name(user_id: int, conn: Optional[psycopg.Connection] = None) -> Optional[str]:
    return get_user_field("id", user_id, "display_name", conn=conn)


def get_user_id(username: str, conn: Optional[psycopg.Connection] = None) -> Optional[int]:
    return get_user_field("username", username, "id", conn=conn)


def get_password_hash(user_id: int, conn: Optional[psycopg.Connection] = None) -> Optional[str]:
    return get_user_field("id", user_id, "password_hash", conn=conn)


def get_created_at(user_id: int, conn: Optional[psycopg.Connection] = None) -> Optional[datetime]:
    return get_user_field("id", user_id, "created_at", conn=conn)


def get_user_avatar_data_url(user_id: int, conn: Optional[psycopg.Connection] = None) -> Optional[str]:
    return get_user_field("id", user_id, "avatar_data_url", conn=conn)


def verify_password(user_id: int, password: str, conn: Optional[psycopg.Connection] = None) -> bool:
    password_hash = get_password_hash(user_id, conn=conn)
    if password_hash is None:
        raise ValueError(f"user_id={user_id} not found")

    return bcrypt.checkpw(
        password.encode("utf-8"),
        password_hash.encode("utf-8"),
    )


def update_user_password(user_id: int, password: str, conn: Optional[psycopg.Connection] = None) -> bool:
    if not password:
        raise ValueError("password cannot be empty/None")

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    updated = update_user_field("id", user_id, "password_hash", password_hash, conn=conn)
    if not updated:
        raise ValueError(f"user_id={user_id} not found")
    return True


def update_user_display_name(user_id: int, display_name: str, conn: Optional[psycopg.Connection] = None) -> bool:
    display_name = display_name.strip()
    if not display_name:
        raise ValueError("display_name must be non-empty")

    updated = update_user_field("id", user_id, "display_name", display_name, conn=conn)
    if not updated:
        raise ValueError(f"user_id={user_id} not found")
    return True


def update_user_avatar_data_url(
    user_id: int, avatar_data_url: Optional[str], conn: Optional[psycopg.Connection] = None
) -> bool:
    v = None if avatar_data_url is None else str(avatar_data_url).strip()
    if v == "":
        v = None
    updated = update_user_field("id", user_id, "avatar_data_url", v, conn=conn)
    if not updated:
        raise ValueError(f"user_id={user_id} not found")
    return True


def delete_user(user_id: int, conn: Optional[psycopg.Connection] = None) -> bool:
    sql = "DELETE FROM users WHERE id = %(user_id)s;"
    rowcount = _exec_and_rowcount(sql, {"user_id": int(user_id)}, conn=conn)
    return rowcount > 0


def create_auth_token(
    user_id: int,
    token_hash: str,
    expires_at: datetime,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    sql = """
    INSERT INTO auth_tokens (user_id, token_hash, expires_at)
    VALUES (%(user_id)s, %(token_hash)s, %(expires_at)s)
    RETURNING id;
    """

    if conn is None:
        with psycopg.connect(_pool.DB_URL) as _conn:
            with _conn.cursor() as cur:
                cur.execute(
                    sql,
                    {"user_id": int(user_id), "token_hash": token_hash, "expires_at": expires_at},
                )
                row = cur.fetchone()
                _conn.commit()
                if row is None:
                    raise RuntimeError("Failed to create auth token (no id returned)")
                return int(row[0])

    with conn.cursor() as cur:
        cur.execute(
            sql,
            {"user_id": int(user_id), "token_hash": token_hash, "expires_at": expires_at},
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("Failed to create auth token (no id returned)")
        return int(row[0])


def get_user_id_by_token_hash(
    token_hash: str,
    conn: Optional[psycopg.Connection] = None,
) -> Optional[int]:
    sql = """
    SELECT user_id
    FROM auth_tokens
    WHERE token_hash = %(token_hash)s
      AND revoked_at IS NULL
      AND expires_at > now()
    LIMIT 1;
    """

    if conn is None:
        with psycopg.connect(_pool.DB_URL) as _conn:
            with _conn.cursor() as cur:
                cur.execute(sql, {"token_hash": token_hash})
                row = cur.fetchone()
                return None if row is None else int(row[0])

    with conn.cursor() as cur:
        cur.execute(sql, {"token_hash": token_hash})
        row = cur.fetchone()
        return None if row is None else int(row[0])


def revoke_token_by_hash(
    token_hash: str,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    sql = """
    UPDATE auth_tokens
    SET revoked_at = now()
    WHERE token_hash = %(token_hash)s
      AND revoked_at IS NULL
    RETURNING id;
    """

    if conn is None:
        with psycopg.connect(_pool.DB_URL) as _conn:
            with _conn.cursor() as cur:
                cur.execute(sql, {"token_hash": token_hash})
                row = cur.fetchone()
                _conn.commit()
                return row is not None

    with conn.cursor() as cur:
        cur.execute(sql, {"token_hash": token_hash})
        row = cur.fetchone()
        return row is not None
