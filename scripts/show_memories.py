"""Show rows from the memories table.

Usage:
  python scripts/show_memories.py
  python scripts/show_memories.py --user-id 1 --all
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from companion.infra import db  # noqa: E402


def _table_exists(cur: psycopg.Cursor) -> bool:
    cur.execute("SELECT to_regclass('public.memories') IS NOT NULL AS table_exists")
    row = cur.fetchone()
    return bool(row and row["table_exists"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Show contents of the memories table.")
    parser.add_argument(
        "--db",
        dest="db_url",
        default=os.getenv("DB_URL", db.DB_URL),
        help="Database URL. Defaults to env DB_URL or companion.infra.db.DB_URL.",
    )
    parser.add_argument("--user-id", type=int, help="Only show memories for one user.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum rows to show. Default: 50.")
    parser.add_argument("--all", action="store_true", help="Show all rows, ignoring --limit.")
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Include inactive memories. By default only active memories are shown.",
    )
    args = parser.parse_args()
    print(f"DB: {args.db_url.split('@')[-1]}")

    where: list[str] = []
    params: dict[str, object] = {}
    if args.user_id is not None:
        where.append("user_id = %(user_id)s")
        params["user_id"] = args.user_id
    if not args.include_inactive:
        where.append("is_active = true")

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    limit_sql = "" if args.all else "LIMIT %(limit)s"
    if not args.all:
        params["limit"] = max(1, args.limit)

    sql = f"""
        SELECT
          id,
          user_id,
          session_id,
          source_message_id,
          memory_type,
          importance,
          is_active,
          created_at,
          updated_at,
          content,
          embedding IS NOT NULL AS has_embedding
        FROM memories
        {where_sql}
        ORDER BY updated_at DESC, id DESC
        {limit_sql};
    """

    try:
        with psycopg.connect(args.db_url, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                if not _table_exists(cur):
                    print("memories table does not exist. Run migration 015_create_memories.sql first.")
                    return 1
                cur.execute(sql, params)
                rows = cur.fetchall()
    except Exception as e:
        print(f"Error reading memories table: {e}", file=sys.stderr)
        return 1

    if not rows:
        print("No memories found.")
        return 0

    print(f"Memories ({len(rows)} row{'s' if len(rows) != 1 else ''}):")
    print()
    for row in rows:
        print(
            f"#{row['id']} user={row['user_id']} session={row['session_id']} "
            f"type={row['memory_type']} importance={row['importance']} "
            f"active={row['is_active']} embedding={row['has_embedding']}"
        )
        print(f"source_message_id={row['source_message_id']}")
        print(f"created_at={row['created_at']} updated_at={row['updated_at']}")
        print(f"content: {row['content']}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
