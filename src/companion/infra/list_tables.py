"""
companion/infra/list_tables.py — CLI to list tables (and optional columns) in Postgres.

Entry: ``python -m companion.infra.list_tables`` [--db URL] [--columns]

Public API:
  main — argparse entry; returns exit code

Internal: (none)
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg

from companion.infra.env_loader import load_repo_dotenv


def main() -> int:
    load_repo_dotenv()
    parser = argparse.ArgumentParser(description="List tables in the companion database.")
    parser.add_argument(
        "--db",
        dest="db_url",
        default=os.getenv("DB_URL", "postgresql://app:app_pw_123@127.0.0.1:5433/companion"),
        help="Database URL. Defaults to env DB_URL or a local fallback.",
    )
    parser.add_argument(
        "--columns",
        action="store_true",
        help="Show columns for each table.",
    )
    args = parser.parse_args()

    sql_tables = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
          AND table_type = 'BASE TABLE'
        ORDER BY table_schema, table_name;
    """
    sql_columns = """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = %(schema)s AND table_name = %(table)s
        ORDER BY ordinal_position;
    """

    try:
        with psycopg.connect(args.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(sql_tables)
                rows = cur.fetchall()

            if not rows:
                print("No tables found.")
                return 0

            db_name = args.db_url.split("@")[-1].split("/")[-1].split("?")[0]
            print(f"Database: {db_name}")
            print(f"Tables ({len(rows)}):")
            print()

            for schema, table in rows:
                name = f"{schema}.{table}" if schema != "public" else table
                print(f"  {name}")
                if args.columns:
                    with conn.cursor() as cur2:
                        cur2.execute(sql_columns, {"schema": schema, "table": table})
                        cols = cur2.fetchall()
                    for col_name, dtype, nullable in cols:
                        null_str = "NULL" if nullable == "YES" else "NOT NULL"
                        print(f"      {col_name}: {dtype} {null_str}")
                print()
    except Exception as e:
        print(f"Error connecting to database: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
