"""
companion/infra/db/pool.py — Connection string, idempotent startup migrations, connection pool.

Public API:
  DB_URL — resolved from env DB_URL with local default
  ensure_relationship_mood_state_v1 — apply migration 010 if mood columns missing
  ensure_bot_initiative_column — add bots.initiative if missing
  ensure_bot_personality_column — add bots.personality if missing; migrate old enum to user-chosen four styles
  init_pool / close_pool — psycopg ConnectionPool lifecycle

Internal:
  _get_conn — context manager: caller conn, pool conn, or direct DB_URL connection
  _pool — module-level pool reference (also re-exported as db._pool)
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

import psycopg
from psycopg_pool import ConnectionPool

from companion.infra.env_loader import load_repo_dotenv

logger = logging.getLogger(__name__)

_COMPANION_ROOT = Path(__file__).resolve().parent.parent.parent

load_repo_dotenv()

DB_URL = os.getenv(
    "DB_URL",
    "postgresql://app:app_pw_123@127.0.0.1:5433/companion",
)


def ensure_relationship_mood_state_v1() -> None:
    """
    If mood v1 columns are missing on relationship_state, run migration 010.
    Idempotent (ADD COLUMN IF NOT EXISTS). Call once at API startup so dev DBs
    match code without manual psql.
    """
    mig = _COMPANION_ROOT / "migrations" / "010_relationship_mood_state_v1.sql"
    if not mig.is_file():
        logger.warning("Mood migration file missing: %s", mig)
        return
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'relationship_state'
                  AND column_name = 'energy'
                LIMIT 1
                """
            )
            if cur.fetchone():
                return
        sql_text = mig.read_text(encoding="utf-8")
        parts = [p.strip() for p in sql_text.split(";") if p.strip()]
        with conn.cursor() as cur:
            for part in parts:
                cur.execute(part + ";")
        conn.commit()
    logger.info("Applied database migration: 010_relationship_mood_state_v1.sql")


def ensure_bot_initiative_column() -> None:
    """Add bots.initiative if missing (idempotent)."""
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'bots'
                  AND column_name = 'initiative'
                LIMIT 1
                """
            )
            if cur.fetchone():
                return
            cur.execute(
                """
                ALTER TABLE bots
                ADD COLUMN initiative TEXT NOT NULL DEFAULT 'medium'
                CHECK (initiative IN ('low', 'medium', 'high'))
                """
            )
        conn.commit()
    logger.info("Applied schema: bots.initiative")


def ensure_bot_personality_column() -> None:
    """Add bots.personality if missing; migrate pre-user-choice enum (lively/cold/default) to playful/cool/gentle."""
    mig_013 = _COMPANION_ROOT / "migrations" / "013_bot_personality_user_choice.sql"
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'bots'
                  AND column_name = 'personality'
                LIMIT 1
                """
            )
            col_exists = cur.fetchone() is not None
            if not col_exists:
                cur.execute(
                    """
                    ALTER TABLE bots
                    ADD COLUMN personality TEXT NOT NULL DEFAULT 'gentle'
                    CHECK (personality IN ('tsundere', 'playful', 'cool', 'gentle'))
                    """
                )
            else:
                cur.execute(
                    """
                    SELECT 1 FROM pg_constraint c
                    JOIN pg_class t ON c.conrelid = t.oid
                    JOIN pg_namespace n ON t.relnamespace = n.oid
                    WHERE n.nspname = 'public' AND t.relname = 'bots' AND c.contype = 'c'
                      AND pg_get_constraintdef(c.oid) LIKE '%playful%'
                    LIMIT 1
                    """
                )
                if cur.fetchone() is None and mig_013.is_file():
                    raw = mig_013.read_text(encoding="utf-8")
                    lines = [ln for ln in raw.splitlines() if not ln.strip().startswith("--")]
                    sql_body = "\n".join(lines).strip()
                    for part in [p.strip() for p in sql_body.split(";") if p.strip()]:
                        cur.execute(part + ";")
        conn.commit()
    logger.info("Ensured bots.personality (game reply style)")


_pool: ConnectionPool | None = None


def init_pool() -> None:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DB_URL,
            min_size=1,
            max_size=5,
            timeout=10,
            open=True,
            kwargs={"autocommit": False},
        )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def _get_conn(conn: Optional[psycopg.Connection] = None) -> Iterator[tuple[psycopg.Connection, bool]]:
    if conn is not None:
        yield conn, False
        return

    if _pool is not None:
        with _pool.connection() as pooled_conn:
            yield pooled_conn, False
            return

    with psycopg.connect(DB_URL) as direct_conn:
        yield direct_conn, True
