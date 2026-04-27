from __future__ import annotations

from typing import Generator

import psycopg
from fastapi import Depends, Header, HTTPException

from companion import service
from companion.infra import db


def get_db_conn() -> Generator[psycopg.Connection, None, None]:
    """
    One connection per request:
    - borrow from pool
    - commit on success
    - rollback on error
    """
    if db._pool is None:
        raise RuntimeError("DB pool not initialized")

    with db._pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def get_current_user_id(
    authorization: str | None = Header(default=None),
    conn: psycopg.Connection = Depends(get_db_conn),
) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    raw_token = authorization.removeprefix("Bearer ").strip()
    try:
        return service.get_user_id_from_token(raw_token, conn=conn)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def get_optional_bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip()
