"""
companion/infra/db/internal.py — Shared SQL helpers and JSON coercions (db package private).

Not imported by application code outside ``companion.infra.db``; used by users, sessions, bots,
messages, relationship modules.

Internal (all underscore-prefixed by convention):
  _MISSING — sentinel for optional UPDATE fields
  _secondary_interests_list, _coerce_prev_turn_triggers_list — parse DB/JSON values
  _prev_turn_triggers_jsonb — build psycopg Json for prev_turn_triggers column
  _fetch_one_value, _fetch_one_row, _fetch_all_rows — read helpers using _get_conn
  _exec_fetch_one_row, _exec_returning_id, _exec_and_rowcount — write helpers with optional commit
"""
from __future__ import annotations

import json
from typing import Any, Mapping, Optional

import psycopg
from psycopg.types.json import Json

from .pool import _get_conn

_MISSING = object()


def _secondary_interests_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return _secondary_interests_list(data)
    return []


def _coerce_prev_turn_triggers_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, str)]
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(data, list):
            return [x for x in data if isinstance(x, str)]
    return []


def _prev_turn_triggers_jsonb(raw: Any) -> Json:
    """JSONB array of trigger id strings; avoids invalid PG JSON from bare Python set/repr."""
    if raw is None:
        return Json([])
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
            raw = data
        except json.JSONDecodeError:
            return Json([])
    if isinstance(raw, dict):
        out = [str(k) for k in raw]
        return Json(out)
    if isinstance(raw, (list, tuple)):
        return Json([str(x) for x in raw])
    if isinstance(raw, (set, frozenset)):
        return Json([str(x) for x in raw])
    return Json([str(raw)])


def _fetch_one_value(
    sql: str,
    params: Mapping[str, Any],
    conn: Optional[psycopg.Connection] = None,
) -> Optional[Any]:
    with _get_conn(conn) as (c, _):
        with c.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return None if row is None else row[0]


def _fetch_one_row(
    sql: str,
    params: Mapping[str, Any],
    conn: Optional[psycopg.Connection] = None,
) -> Optional[tuple]:
    with _get_conn(conn) as (c, _):
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()


def _exec_fetch_one_row(
    sql: str,
    params: Mapping[str, Any],
    conn: Optional[psycopg.Connection] = None,
) -> tuple | None:
    with _get_conn(conn) as (c, should_commit):
        with c.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        if should_commit:
            c.commit()
        return row


def _fetch_all_rows(
    sql: str,
    params: Mapping[str, Any],
    conn: Optional[psycopg.Connection] = None,
) -> list[tuple]:
    with _get_conn(conn) as (c, _):
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def _exec_returning_id(
    sql: str,
    params: Mapping[str, Any],
    conn: Optional[psycopg.Connection] = None,
) -> int:
    with _get_conn(conn) as (c, should_commit):
        with c.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("INSERT failed: no row returned")
        if should_commit:
            c.commit()
        return row[0]


def _exec_and_rowcount(
    sql: str,
    params: Mapping[str, Any],
    conn: Optional[psycopg.Connection] = None,
) -> int:
    with _get_conn(conn) as (c, should_commit):
        with c.cursor() as cur:
            cur.execute(sql, params)
            rc = cur.rowcount
        if should_commit:
            c.commit()
        return rc
