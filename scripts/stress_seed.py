"""
Seed a separate stress Neon DB with load-test users, bots (sessions), and messages.

Usage (from repo root):
  $env:STRESS_DB_URL = "postgresql://..."
  $env:PYTHONPATH = "$PWD\\src"
  python scripts/stress_seed.py
  python scripts/stress_seed.py --force   # wipe loadtest_* users first
"""
from __future__ import annotations

import argparse
import sys

import psycopg

from stress_common import (
    BOTS_PER_USER,
    NUM_USERS,
    USER_PREFIX,
    bot_name,
    configure_db_layer,
    loadtest_display_name,
    loadtest_password,
    loadtest_username,
    resolve_stress_db_url,
)

from companion.infra import db  # noqa: E402

TOTAL_BOTS = NUM_USERS * BOTS_PER_USER  # 200 sessions
TOTAL_MESSAGES = 6200
MESSAGES_PER_SESSION = TOTAL_MESSAGES // TOTAL_BOTS  # 31


def _count_loadtest_rows(conn: psycopg.Connection) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM users WHERE username LIKE %s", (f"{USER_PREFIX}%",))
        users = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM bots b
            JOIN users u ON u.id = b.user_id
            WHERE u.username LIKE %s
            """,
            (f"{USER_PREFIX}%",),
        )
        bots = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM messages m
            JOIN users u ON u.id = m.user_id
            WHERE u.username LIKE %s
            """,
            (f"{USER_PREFIX}%",),
        )
        messages = int(cur.fetchone()[0])
        cur.execute(
            """
            SELECT COUNT(*) FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE u.username LIKE %s
            """,
            (f"{USER_PREFIX}%",),
        )
        sessions = int(cur.fetchone()[0])
    return {"users": users, "bots": bots, "sessions": sessions, "messages": messages}


def _delete_loadtest_users(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE username LIKE %s", (f"{USER_PREFIX}%",))
        ids = [row[0] for row in cur.fetchall()]
        for uid in ids:
            cur.execute("DELETE FROM bots WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
    conn.commit()
    return len(ids)


def _seed(conn: psycopg.Connection, *, resume: bool = False) -> None:
    password = loadtest_password()
    msg_index = 0
    existing = _count_loadtest_rows(conn)["messages"] if resume else 0
    msg_index = existing

    for user_i in range(NUM_USERS):
        username = loadtest_username(user_i)
        if resume and db.get_user_id(username, conn=conn) is not None:
            print(f"  skip user {user_i + 1}/{NUM_USERS} ({username}) — already exists")
            continue
        user_id = db.create_user(loadtest_display_name(user_i), username, password, conn=conn)

        for bot_i in range(BOTS_PER_USER):
            session_id = db.create_session(user_id, conn=conn)
            bot_id = db.create_bot(
                user_id,
                session_id,
                name=bot_name(user_i, bot_i),
                system_prompt="You are a load-test companion bot.",
                direction="a helpful, friendly companion",
                primary_interest="gaming",
                secondary_interests=[],
                conn=conn,
            )
            db.get_or_create_relationship(user_id, bot_id, conn=conn)

            for m in range(MESSAGES_PER_SESSION):
                role = "user" if m % 2 == 0 else "assistant"
                content = f"[loadtest] user={user_i} bot={bot_i} msg={m} role={role}"
                db.create_message(user_id, session_id, role, content, conn=conn)
                msg_index += 1

        conn.commit()
        print(f"  user {user_i + 1}/{NUM_USERS} ({username}) — {BOTS_PER_USER} bots, messages so far: {msg_index}")

    final = _count_loadtest_rows(conn)
    if final["messages"] != TOTAL_MESSAGES:
        raise RuntimeError(
            f"expected {TOTAL_MESSAGES} messages total, have {final['messages']} "
            f"(users={final['users']}, bots={final['bots']})"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed stress DB with load-test data.")
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"Delete existing users matching {USER_PREFIX}% before seeding.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Create only missing loadtest users (skip existing usernames).",
    )
    args = parser.parse_args()
    if args.force and args.resume:
        print("Use either --force or --resume, not both.", file=sys.stderr)
        return 2

    stress_url = resolve_stress_db_url()
    configure_db_layer(stress_url)

    with psycopg.connect(stress_url) as conn:
        counts = _count_loadtest_rows(conn)
        if counts["users"] > 0 and not args.force and not args.resume:
            print("Load-test data already exists (use --force to wipe and re-seed, or --resume to fill gaps):")
            for k, v in counts.items():
                print(f"  {k}: {v}")
            print(f"\nSample login: {loadtest_username(0)} / (see STRESS_LOADTEST_PASSWORD or default)")
            return 0

        if args.force and counts["users"] > 0:
            removed = _delete_loadtest_users(conn)
            print(f"Removed {removed} load-test user(s).")

        if args.resume and counts["messages"] >= TOTAL_MESSAGES:
            print("Already at target counts:")
            for k, v in counts.items():
                print(f"  {k}: {v}")
            return 0

        print(
            f"Seeding {NUM_USERS} users, {TOTAL_BOTS} bots/sessions, "
            f"{TOTAL_MESSAGES} messages ({MESSAGES_PER_SESSION} per session)"
            f"{', resume mode' if args.resume else ''}..."
        )
        _seed(conn, resume=args.resume)
        counts = _count_loadtest_rows(conn)
        print("\nDone. Final counts:")
        for k, v in counts.items():
            print(f"  {k}: {v}")
        print(f"\nSample login: {loadtest_username(0)} / {loadtest_password()!r}")
        print(f"Usernames: {loadtest_username(0)} … {loadtest_username(NUM_USERS - 1)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
