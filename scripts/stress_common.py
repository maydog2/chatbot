"""Shared helpers for stress seed / load / cleanup scripts."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from companion.infra import db  # noqa: E402
from companion.infra.db import pool as pool_mod  # noqa: E402

USER_PREFIX = "loadtest_u"
NUM_USERS = 20
BOTS_PER_USER = 10
DEFAULT_PASSWORD_ENV = "STRESS_LOADTEST_PASSWORD"
DEFAULT_PASSWORD = "LoadTest!Abc123"


def load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def resolve_stress_db_url() -> str:
    load_dotenv_if_available()
    stress_url = (os.getenv("STRESS_DB_URL") or "").strip()
    if not stress_url:
        raise SystemExit(
            "STRESS_DB_URL is not set. Create a Neon branch, copy the pooled connection string, "
            "and export STRESS_DB_URL before running stress scripts."
        )
    prod_url = (os.getenv("DB_URL") or "").strip()
    if prod_url and stress_url == prod_url:
        raise SystemExit(
            "STRESS_DB_URL must not equal DB_URL (refusing to run against production database)."
        )
    return stress_url


def configure_db_layer(stress_url: str) -> None:
    pool_mod.DB_URL = stress_url
    db.DB_URL = stress_url


def loadtest_password() -> str:
    load_dotenv_if_available()
    return (os.getenv(DEFAULT_PASSWORD_ENV) or DEFAULT_PASSWORD).strip()


def loadtest_username(index: int) -> str:
    return f"{USER_PREFIX}{index:02d}"


def loadtest_display_name(index: int) -> str:
    return f"Load Test User {index:02d}"


def bot_name(user_index: int, bot_index: int) -> str:
    return f"LoadBot-{user_index:02d}-{bot_index:02d}"
