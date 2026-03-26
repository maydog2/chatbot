import pytest
import uuid
import sys
import os
from pathlib import Path

# Add <project_root>/src to sys.path so tests can import our src-layout package
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from companion.infra import db
from companion.infra.db import pool as pool_mod

def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

@pytest.fixture(scope="session", autouse=True)
def _use_test_db_and_reset_schema():
    """
    Force all tests to use the test database, and reset schema once per test session.
    """
    test_db_url = os.getenv(
        "TEST_DB_URL",
        "postgresql://app:app_pw_123@127.0.0.1:5433/companion_test",
    )

    # Force db layer to use the test DB (pool + package re-export stay in sync)
    pool_mod.DB_URL = test_db_url
    db.DB_URL = test_db_url

    # Run reset.sql to ensure a clean schema for the whole test run
    # (Requires companion/reset.sql to exist under src/companion/)
    reset_sql_path = PROJECT_ROOT / "src" / "companion" / "reset.sql"
    sql_text = reset_sql_path.read_text(encoding="utf-8")

    import psycopg
    with psycopg.connect(test_db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        conn.commit()

@pytest.fixture
def user():
    display_name = _uniq("dn")
    username = _uniq("test_u")
    password = "Abcdefg123!@#"
    user_id = db.create_user(display_name, username, password)
    yield {"id": user_id, "username": username, "password": password, "display_name": display_name}

    # Best-effort cleanup (may fail if FK constraints prevent deletion)
    try:
        db.delete_user(user_id)
    except Exception:
        pass