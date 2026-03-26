"""
companion/infra/db/bots.py — ``bots`` table (one row per bot, bound to a session_id).

Public API:
  user_has_duplicate_bot_name, user_has_duplicate_bot_avatar — uniqueness checks per user
  create_bot, get_bot, get_bots_by_user, update_bot, delete_bot — CRUD (delete also removes session)

Internal: (none at function level; uses _MISSING and helpers from internal.py)
"""
from __future__ import annotations

from typing import Optional

import psycopg
from psycopg.types.json import Json

from .internal import (
    _MISSING,
    _exec_and_rowcount,
    _exec_returning_id,
    _fetch_all_rows,
    _fetch_one_row,
    _fetch_one_value,
    _secondary_interests_list,
)


def user_has_duplicate_bot_name(
    user_id: int,
    name: str,
    *,
    exclude_bot_id: Optional[int] = None,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    """Same user cannot reuse a bot name (case-insensitive, trimmed)."""
    user_id = int(user_id)
    name_s = (name or "").strip()
    if not name_s:
        return False
    if exclude_bot_id is None:
        sql = """
        SELECT EXISTS(
            SELECT 1 FROM bots
            WHERE user_id = %(user_id)s
              AND lower(trim(name)) = lower(trim(%(name)s))
        )
        """
        params: dict[str, object] = {"user_id": user_id, "name": name_s}
    else:
        sql = """
        SELECT EXISTS(
            SELECT 1 FROM bots
            WHERE user_id = %(user_id)s
              AND id <> %(exclude_bot_id)s
              AND lower(trim(name)) = lower(trim(%(name)s))
        )
        """
        params = {"user_id": user_id, "name": name_s, "exclude_bot_id": int(exclude_bot_id)}
    return bool(_fetch_one_value(sql, params, conn=conn))


def user_has_duplicate_bot_avatar(
    user_id: int,
    avatar_data_url: str,
    *,
    exclude_bot_id: Optional[int] = None,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    """Same user cannot reuse the same avatar image (exact data URL match). Ignores empty/null."""
    user_id = int(user_id)
    av = (avatar_data_url or "").strip()
    if not av:
        return False
    if exclude_bot_id is None:
        sql = """
        SELECT EXISTS(
            SELECT 1 FROM bots
            WHERE user_id = %(user_id)s
              AND avatar_data_url = %(avatar)s
        )
        """
        params: dict[str, object] = {"user_id": user_id, "avatar": av}
    else:
        sql = """
        SELECT EXISTS(
            SELECT 1 FROM bots
            WHERE user_id = %(user_id)s
              AND id <> %(exclude_bot_id)s
              AND avatar_data_url = %(avatar)s
        )
        """
        params = {"user_id": user_id, "avatar": av, "exclude_bot_id": int(exclude_bot_id)}
    return bool(_fetch_one_value(sql, params, conn=conn))


def create_bot(
    user_id: int,
    session_id: int,
    name: str,
    system_prompt: str,
    avatar_data_url: Optional[str] = None,
    direction: Optional[str] = None,
    form_of_address: Optional[str] = None,
    primary_interest: Optional[str] = None,
    secondary_interests: Optional[list[str]] = None,
    initiative: str = "medium",
    conn: Optional[psycopg.Connection] = None,
) -> int:
    user_id = int(user_id)
    session_id = int(session_id)
    sec = secondary_interests if secondary_interests is not None else []
    sql = """
        INSERT INTO bots (user_id, session_id, name, system_prompt, avatar_data_url, direction, form_of_address, primary_interest, secondary_interests, initiative)
        VALUES (%(user_id)s, %(session_id)s, %(name)s, %(system_prompt)s, %(avatar_data_url)s, %(direction)s, %(form_of_address)s, %(primary_interest)s, %(secondary_interests)s, %(initiative)s)
        RETURNING id;
        """
    return _exec_returning_id(
        sql,
        {
            "user_id": user_id,
            "session_id": session_id,
            "name": name,
            "system_prompt": system_prompt,
            "avatar_data_url": avatar_data_url,
            "direction": direction,
            "form_of_address": form_of_address,
            "primary_interest": primary_interest,
            "secondary_interests": Json(sec),
            "initiative": initiative,
        },
        conn=conn,
    )


def get_bot(
    bot_id: int,
    user_id: Optional[int] = None,
    conn: Optional[psycopg.Connection] = None,
) -> Optional[dict]:
    bot_id = int(bot_id)
    if user_id is not None:
        sql = "SELECT id, user_id, session_id, name, system_prompt, avatar_data_url, direction, form_of_address, primary_interest, secondary_interests, initiative, created_at FROM bots WHERE id = %(bot_id)s AND user_id = %(user_id)s;"
        row = _fetch_one_row(sql, {"bot_id": bot_id, "user_id": int(user_id)}, conn=conn)
    else:
        sql = "SELECT id, user_id, session_id, name, system_prompt, avatar_data_url, direction, form_of_address, primary_interest, secondary_interests, initiative, created_at FROM bots WHERE id = %(bot_id)s;"
        row = _fetch_one_row(sql, {"bot_id": bot_id}, conn=conn)
    if row is None:
        return None
    return {
        "id": row[0],
        "user_id": row[1],
        "session_id": row[2],
        "name": row[3],
        "system_prompt": row[4],
        "avatar_data_url": row[5],
        "direction": row[6],
        "form_of_address": row[7],
        "primary_interest": row[8],
        "secondary_interests": _secondary_interests_list(row[9]),
        "initiative": row[10],
        "created_at": row[11],
    }


def get_bots_by_user(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    user_id = int(user_id)
    sql = """
        SELECT id, user_id, session_id, name, system_prompt, avatar_data_url, direction, form_of_address, primary_interest, secondary_interests, initiative, created_at
        FROM bots
        WHERE user_id = %(user_id)s
        ORDER BY created_at ASC;
        """
    rows = _fetch_all_rows(sql, {"user_id": user_id}, conn=conn)
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "session_id": r[2],
            "name": r[3],
            "system_prompt": r[4],
            "avatar_data_url": r[5],
            "direction": r[6],
            "form_of_address": r[7],
            "primary_interest": r[8],
            "secondary_interests": _secondary_interests_list(r[9]),
            "initiative": r[10],
            "created_at": r[11],
        }
        for r in rows
    ]


def update_bot(
    bot_id: int,
    user_id: int,
    *,
    name: object = _MISSING,
    direction: object = _MISSING,
    system_prompt: object = _MISSING,
    avatar_data_url: object = _MISSING,
    form_of_address: object = _MISSING,
    primary_interest: object = _MISSING,
    secondary_interests: object = _MISSING,
    initiative: object = _MISSING,
    conn: Optional[psycopg.Connection] = None,
) -> Optional[dict]:
    """
    Update bot fields. Pass _MISSING to leave a field unchanged.
    Passing None explicitly will set the DB value to NULL (where allowed).
    Returns updated bot dict, or None if not found.
    """
    bot_id = int(bot_id)
    user_id = int(user_id)

    sets: list[str] = []
    params: dict[str, object] = {"bot_id": bot_id, "user_id": user_id}

    if name is not _MISSING:
        name_s = str(name).strip()
        if not name_s:
            raise ValueError("name must be non-empty")
        sets.append("name = %(name)s")
        params["name"] = name_s

    if direction is not _MISSING:
        params["direction"] = None if direction is None else str(direction)
        sets.append("direction = %(direction)s")

    if system_prompt is not _MISSING:
        sp = "" if system_prompt is None else str(system_prompt)
        if not sp.strip():
            raise ValueError("system_prompt must be non-empty")
        sets.append("system_prompt = %(system_prompt)s")
        params["system_prompt"] = sp

    if avatar_data_url is not _MISSING:
        params["avatar_data_url"] = None if avatar_data_url is None else str(avatar_data_url)
        sets.append("avatar_data_url = %(avatar_data_url)s")

    if form_of_address is not _MISSING:
        params["form_of_address"] = None if form_of_address is None else str(form_of_address)
        sets.append("form_of_address = %(form_of_address)s")

    if primary_interest is not _MISSING:
        params["primary_interest"] = None if primary_interest is None else str(primary_interest)
        sets.append("primary_interest = %(primary_interest)s")

    if secondary_interests is not _MISSING:
        if secondary_interests is None:
            params["secondary_interests"] = Json([])
        elif isinstance(secondary_interests, list):
            params["secondary_interests"] = Json([str(x) for x in secondary_interests])
        else:
            raise ValueError("secondary_interests must be a list or None")
        sets.append("secondary_interests = %(secondary_interests)s")

    if initiative is not _MISSING:
        ini = ("" if initiative is None else str(initiative)).strip().lower()
        if ini not in ("low", "medium", "high"):
            raise ValueError("initiative must be low, medium, or high")
        params["initiative"] = ini
        sets.append("initiative = %(initiative)s")

    if not sets:
        return get_bot(bot_id, user_id=user_id, conn=conn)

    sql = f"""
        UPDATE bots
        SET {", ".join(sets)}
        WHERE id = %(bot_id)s AND user_id = %(user_id)s
        RETURNING id;
    """
    updated_id = _fetch_one_value(sql, params, conn=conn)
    if updated_id is None:
        return None
    return get_bot(int(updated_id), user_id=user_id, conn=conn)


def delete_bot(bot_id: int, user_id: int, conn: Optional[psycopg.Connection] = None) -> bool:
    """Delete bot and its session (messages CASCADE). Returns True if bot was found and deleted."""
    bot_id = int(bot_id)
    user_id = int(user_id)
    bot = get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        return False
    session_id = bot["session_id"]
    sql_bot = "DELETE FROM bots WHERE id = %(bot_id)s AND user_id = %(user_id)s;"
    _exec_and_rowcount(sql_bot, {"bot_id": bot_id, "user_id": user_id}, conn=conn)
    sql_sess = "DELETE FROM sessions WHERE id = %(session_id)s;"
    _exec_and_rowcount(sql_sess, {"session_id": session_id}, conn=conn)
    return True
