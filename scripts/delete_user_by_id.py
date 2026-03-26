"""One-off: delete a user and dependent rows (bots first because of session RESTRICT). Usage:
  python scripts/delete_user_by_id.py 2
"""
from __future__ import annotations

import os
import sys

import psycopg

DB_URL = os.environ.get("DB_URL", "postgresql://app:app_pw_123@127.0.0.1:5433/companion")


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("Usage: python scripts/delete_user_by_id.py <user_id>", file=sys.stderr)
        return 2
    uid = int(sys.argv[1])
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, username, display_name FROM users WHERE id = %s", (uid,))
            row = cur.fetchone()
            if row is None:
                print(f"No user with id={uid}")
                return 1
            print(f"Deleting user id={row[0]} username={row[1]!r} display_name={row[2]!r}")
            cur.execute("DELETE FROM bots WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.commit()
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
