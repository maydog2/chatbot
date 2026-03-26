"""Quick diagnostics: users, bots counts, interest columns."""
import os
import psycopg

url = os.environ.get("DB_URL", "postgresql://app:app_pw_123@127.0.0.1:5433/companion")
with psycopg.connect(url) as c:
    with c.cursor() as cur:
        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'bots'
              AND column_name IN ('primary_interest','secondary_interests')
            ORDER BY column_name
            """
        )
        print("bots interest columns present:", [r[0] for r in cur.fetchall()])
        cur.execute("SELECT id, username, display_name FROM users ORDER BY id")
        print("users:", cur.fetchall())
        try:
            cur.execute("SELECT COUNT(*) FROM bots")
            print("total bots:", cur.fetchone()[0])
            cur.execute(
                "SELECT user_id, id, name FROM bots ORDER BY user_id, id"
            )
            print("bots:", cur.fetchall())
        except Exception as e:
            print("bots table query failed:", e)
