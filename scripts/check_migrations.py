"""Check which SQL migrations appear to be applied.

This project does not keep a schema_migrations table, so this script checks the
schema/data effects that each migration is expected to leave behind.

Usage:
  python scripts/check_migrations.py
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from companion.infra import db  # noqa: E402

CHECKS: list[tuple[str, str, str]] = [
    ("001", "bots table", "SELECT to_regclass('public.bots') IS NOT NULL"),
    (
        "001",
        "sessions.bot_id dropped",
        """
        SELECT NOT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'sessions' AND column_name = 'bot_id'
        )
        """,
    ),
    (
        "002",
        "relationship_state.bot_id",
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'relationship_state' AND column_name = 'bot_id'
        )
        """,
    ),
    (
        "004",
        "users.avatar_data_url",
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'avatar_data_url'
        )
        """,
    ),
    (
        "005",
        "relationship mood bias columns",
        """
        SELECT
          EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'relationship_state'
              AND column_name = 'mood_recent_bias'
          )
          AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'relationship_state'
              AND column_name = 'prev_turn_triggers'
          )
        """,
    ),
    (
        "006",
        "bots.form_of_address",
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'bots' AND column_name = 'form_of_address'
        )
        """,
    ),
    (
        "007",
        "users.username unique index",
        """
        SELECT EXISTS (
          SELECT 1 FROM pg_indexes
          WHERE schemaname = 'public' AND tablename = 'users' AND indexname = 'users_username_key'
        )
        """,
    ),
    (
        "008",
        "bot interest columns",
        """
        SELECT
          EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'bots' AND column_name = 'primary_interest'
          )
          AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'bots' AND column_name = 'secondary_interests'
          )
        """,
    ),
    (
        "009",
        "no blank bot primary_interest",
        "SELECT NOT EXISTS (SELECT 1 FROM bots WHERE primary_interest IS NULL OR btrim(primary_interest) = '')",
    ),
    (
        "010",
        "relationship mood state v1 columns",
        """
        SELECT
          EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'relationship_state' AND column_name = 'energy'
          )
          AND EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'relationship_state'
              AND column_name = 'last_mood_update_at'
          )
        """,
    ),
    (
        "011",
        "bots.initiative",
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'bots' AND column_name = 'initiative'
        )
        """,
    ),
    (
        "012/013",
        "bots.personality",
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.columns
          WHERE table_schema = 'public' AND table_name = 'bots' AND column_name = 'personality'
        )
        """,
    ),
    (
        "014",
        "bots.session_id unique constraint",
        """
        SELECT EXISTS (
          SELECT 1 FROM pg_constraint
          WHERE conrelid = 'bots'::regclass AND conname = 'bots_session_id_unique'
        )
        """,
    ),
    ("015", "memories table", "SELECT to_regclass('public.memories') IS NOT NULL"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Check migration effects in the companion database.")
    parser.add_argument(
        "--db",
        dest="db_url",
        default=os.getenv("DB_URL", db.DB_URL),
        help="Database URL. Defaults to env DB_URL or companion.infra.db.DB_URL.",
    )
    args = parser.parse_args()

    try:
        with psycopg.connect(args.db_url) as conn:
            with conn.cursor() as cur:
                print(f"DB: {args.db_url.split('@')[-1]}")
                print()
                for number, label, sql in CHECKS:
                    try:
                        cur.execute(sql)
                        applied = bool(cur.fetchone()[0])
                    except Exception as e:
                        print(f"ERR  {number} {label}: {e}")
                        continue
                    status = "OK  " if applied else "MISS"
                    print(f"{status} {number} {label}")
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        return 1

    print()
    print("Note: this infers status from schema/data effects; the project has no migration history table.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
