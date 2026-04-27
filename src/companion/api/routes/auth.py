from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from companion import service
from companion.api.deps import get_db_conn, get_optional_bearer_token
from companion.api.schemas.auth import LoginIn, RegisterIn

router = APIRouter(prefix="/users", tags=["auth"])


@router.post("/register")
def register(payload: RegisterIn, conn: psycopg.Connection = Depends(get_db_conn)):
    try:
        user_id = service.register_user(payload.display_name, payload.username, payload.password, conn=conn)  # type: ignore
        return {"user_id": user_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login")
def login(payload: LoginIn, conn: psycopg.Connection = Depends(get_db_conn)):
    try:
        return service.issue_access_token(
            payload.username, payload.password, remember_me=payload.remember_me, conn=conn
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid username or password")


@router.post("/logout")
def logout(
    conn: psycopg.Connection = Depends(get_db_conn),
    raw_token: str | None = Depends(get_optional_bearer_token),
):
    """Invalidate the current token (log out). Returns a 200 status code if no token exists or the token has expired."""
    if not raw_token:
        return {"revoked": False}
    revoked = service.logout(raw_token, conn=conn)  # type: ignore
    return {"revoked": revoked}
