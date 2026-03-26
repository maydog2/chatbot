"""
companion/service/auth_tokens.py — Bearer access tokens (HMAC hash stored in DB).

Public API:
  issue_access_token — login + mint token + persist hash; returns access_token payload dict
  get_user_id_from_token — resolve user_id from raw bearer token or raise
  logout — revoke token by hash; returns whether a row was updated

Internal:
  _hash_token — HMAC-SHA256 of raw token (used only inside this module)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import psycopg

from companion.infra import db

from .users import login


def _hash_token(raw_token: str) -> str:
    """
    Hash raw token using HMAC-SHA256 with a server secret.
    Never store raw token in DB; store only this hash.
    """
    secret = os.getenv("AUTH_TOKEN_SECRET")
    if not secret:
        raise RuntimeError("AUTH_TOKEN_SECRET is not set")

    mac = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return mac.hexdigest()


def issue_access_token(
    username: str,
    password: str,
    remember_me: bool = True,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    user_id = login(username, password, conn=conn)
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    default_ttl = 30 * 24 * 3600 if remember_me else 7 * 24 * 3600
    ttl_seconds = int(os.getenv("AUTH_TOKEN_TTL_SECONDS", str(default_ttl)))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    db.create_auth_token(user_id=user_id, token_hash=token_hash, expires_at=expires_at, conn=conn)
    return {
        "access_token": raw_token,
        "token_type": "bearer",
        "expires_at": expires_at.isoformat(),
    }


def get_user_id_from_token(
    raw_token: str,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    if not raw_token or not raw_token.strip():
        raise ValueError("missing token")

    token_hash = _hash_token(raw_token)
    user_id = db.get_user_id_by_token_hash(token_hash, conn=conn)
    if user_id is None:
        raise ValueError("invalid or expired token")
    return int(user_id)


def logout(
    raw_token: str,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    """
    Revoke the token (logout).

    Returns:
        True if the token was revoked (row updated),
        False if token not found or already revoked.
    """
    if not raw_token or not raw_token.strip():
        return False

    token_hash = _hash_token(raw_token)
    return db.revoke_token_by_hash(token_hash, conn=conn)
