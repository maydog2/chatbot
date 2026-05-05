"""Apply one SQL migration file without requiring psql.

Usage:
  python scripts/apply_migration.py 012_bot_personality.sql
  python scripts/apply_migration.py src/companion/migrations/015_create_memories.sql
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

MIGRATIONS_DIR = REPO_ROOT / "src" / "companion" / "migrations"


def _migration_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        direct = REPO_ROOT / path
        if direct.is_file():
            return direct
        migration_file = MIGRATIONS_DIR / raw_path
        if migration_file.is_file():
            return migration_file
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a SQL migration using psycopg.")
    parser.add_argument("migration", help="Migration filename or path.")
    parser.add_argument(
        "--db",
        dest="db_url",
        default=os.getenv("DB_URL", db.DB_URL),
        help="Database URL. Defaults to env DB_URL or companion.infra.db.DB_URL.",
    )
    args = parser.parse_args()

    migration_path = _migration_path(args.migration)
    if not migration_path.is_file():
        print(f"Migration file not found: {migration_path}", file=sys.stderr)
        return 2

    sql = migration_path.read_text(encoding="utf-8")
    try:
        with psycopg.connect(args.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
    except Exception as e:
        print(f"Error applying {migration_path.name}: {e}", file=sys.stderr)
        return 1

    print(f"Applied migration: {migration_path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
