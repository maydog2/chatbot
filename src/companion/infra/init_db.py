"""
companion/infra/init_db.py — CLI to apply schema.sql or reset.sql to Postgres.

Entry: ``python -m companion.infra.init_db`` [--db URL] [--reset] [--dir SQL_DIR]

Public API:
  main — argparse entry; returns exit code (0 ok, non-zero on error)

Internal:
  _read_sql — load SQL file text with existence/empty checks

Default SQL directory: companion package root (parent of infra/), unless --dir is passed.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import psycopg

from companion.infra.env_loader import load_repo_dotenv


def _read_sql(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"SQL file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"SQL file is empty: {path}")
    return text


def main() -> int:
    load_repo_dotenv()
    parser = argparse.ArgumentParser(description="Initialize the companion database schema.")
    parser.add_argument(
        "--db",
        dest="db_url",
        default=os.getenv("DB_URL", "postgresql://app:app_pw_123@127.0.0.1:5433/companion"),
        help="Database URL. Defaults to env DB_URL or a local fallback.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="DANGER: Drop tables and recreate from reset.sql (dev/test only).",
    )
    parser.add_argument(
        "--dir",
        dest="sql_dir",
        default=None,
        help="Directory that contains schema.sql/reset.sql. Default: companion package root (parent of infra/).",
    )
    args = parser.parse_args()

    base_dir = Path(args.sql_dir) if args.sql_dir else Path(__file__).resolve().parent.parent
    sql_file = base_dir / ("reset.sql" if args.reset else "schema.sql")

    sql_text = _read_sql(sql_file)

    print(f"[init_db] DB_URL = {args.db_url}")
    print(f"[init_db] Using SQL = {sql_file}")

    # Run the SQL as a single batch.
    # psycopg/libpq supports multiple statements separated by semicolons.
    with psycopg.connect(args.db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        conn.commit()

    print("[init_db] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())