"""
Remove load-test users (username loadtest_*) from the stress Neon DB.

Usage:
  $env:STRESS_DB_URL = "postgresql://..."
  python scripts/stress_cleanup.py
"""
from __future__ import annotations

import argparse

import psycopg

from stress_common import USER_PREFIX, configure_db_layer, resolve_stress_db_url


def _delete_loadtest_users(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id, username FROM users WHERE username LIKE %s ORDER BY id", (f"{USER_PREFIX}%",))
        rows = cur.fetchall()
        for uid, username in rows:
            cur.execute("DELETE FROM bots WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
            print(f"  deleted {username} (id={uid})")
    conn.commit()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete load-test users from stress DB.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompt.",
    )
    args = parser.parse_args()

    stress_url = resolve_stress_db_url()
    configure_db_layer(stress_url)

    with psycopg.connect(stress_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users WHERE username LIKE %s", (f"{USER_PREFIX}%",))
            count = int(cur.fetchone()[0])
        if count == 0:
            print(f"No users matching {USER_PREFIX}% found.")
            return 0

        if not args.yes:
            print(f"About to delete {count} user(s) matching {USER_PREFIX}% from stress DB.")
            answer = input("Type 'yes' to continue: ").strip().lower()
            if answer != "yes":
                print("Aborted.")
                return 1

        removed = _delete_loadtest_users(conn)
        print(f"\nRemoved {removed} user(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
