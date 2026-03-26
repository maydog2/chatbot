# tests/test_api_smoke.py
from __future__ import annotations

from pathlib import Path
import pytest
import psycopg
from fastapi.testclient import TestClient

from companion.infra import db
from companion.api import app


# -------------------------
# Auth env (lifespan requires AUTH_TOKEN_SECRET)
# -------------------------
@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test_secret_very_long_string")
    monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")


@pytest.fixture(autouse=True)
def _stub_llm_for_smoke(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("companion.infra.llm.get_reply", lambda messages: "smoke stub reply")


# -------------------------
# Helpers: reset DB per test
# -------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESET_SQL_PATH = PROJECT_ROOT / "src" / "companion" / "reset.sql"


def _reset_db() -> None:
    """
    Re-run reset.sql to guarantee a clean DB state for each test.
    This avoids having to know table names (TRUNCATE order/FKs).
    """
    if not RESET_SQL_PATH.exists():
        raise RuntimeError(f"reset.sql not found at: {RESET_SQL_PATH}")

    if not getattr(db, "DB_URL", None):
        raise RuntimeError("db.DB_URL is not set. Ensure conftest sets TEST_DB_URL -> db.DB_URL.")

    sql_text = RESET_SQL_PATH.read_text(encoding="utf-8")
    with psycopg.connect(db.DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        conn.commit()


@pytest.fixture()
def client():
    # Ensure a clean schema+data before each test
    _reset_db()
    with TestClient(app) as c:
        yield c
    # Best-effort cleanup after each test as well
    _reset_db()


# -------------------------
# Helpers: API calls
# -------------------------
def _register(client: TestClient, display_name: str, username: str, password: str) -> int:
    r = client.post(
        "/users/register",
        json={"display_name": display_name, "username": username, "password": password},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "user_id" in body
    return int(body["user_id"])


def _create_bot(client: TestClient, auth_headers: dict[str, str], name: str = "smoke_bot", direction: str = "test") -> dict:
    r = client.post(
        "/bots",
        json={"name": name, "direction": direction, "primary_interest": "anime"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _auth_headers(client: TestClient, username: str, password: str) -> dict[str, str] | None:
    """Login and return Authorization header."""
    r = client.post("/users/login", json={"username": username, "password": password})
    if r.status_code != 200:
        return None
    body = r.json()
    token = body.get("access_token")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _send_bot(
    client: TestClient,
    bot_id: int,
    content: str,
    *,
    trust_delta: int = 0,
    resonance_delta: int = 0,
    auth_headers: dict[str, str] | None = None,
):
    assert auth_headers is not None, "smoke tests require auth"
    r = client.post(
        "/chat/send-bot-message",
        json={
            "bot_id": bot_id,
            "content": content,
            "system_prompt": "",
            "trust_delta": trust_delta,
            "resonance_delta": resonance_delta,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _history_bot(
    client: TestClient,
    bot_id: int,
    limit: int = 50,
    *,
    auth_headers: dict[str, str] | None = None,
):
    assert auth_headers is not None, "smoke tests require auth"
    r = client.post(
        "/chat/history/bot",
        json={"bot_id": bot_id, "limit": limit},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "messages" in body
    assert isinstance(body["messages"], list)
    return body["messages"]


# -------------------------
# Smoke tests
# -------------------------
def test_register_login_send_history_end_relationship_smoke(client: TestClient):
    user_id = _register(client, "dn", "u1", "pw123")
    auth = _auth_headers(client, "u1", "pw123")
    assert auth is not None
    bot = _create_bot(client, auth)
    bot_id = int(bot["id"])

    send_res = _send_bot(
        client, bot_id, "hello", trust_delta=1, resonance_delta=2, auth_headers=auth
    )
    assert isinstance(send_res, dict)

    msgs = _history_bot(client, bot_id, limit=50, auth_headers=auth)
    assert len(msgs) >= 1

    r = client.get(f"/bots/{bot_id}/relationship", headers=auth)
    assert r.status_code == 200, r.text
    rel = r.json()
    assert "trust" in rel and "resonance" in rel

    # end session endpoint should respond
    r = client.post("/chat/end", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "ended" in body
    assert isinstance(body["ended"], bool)


def test_register_validation_422(client: TestClient):
    # Missing required field: display_name
    r = client.post("/users/register", json={"username": "u", "password": "p"})
    assert r.status_code == 422


def test_login_wrong_password_401(client: TestClient):
    _register(client, "dn", "u1", "pw1")
    r = client.post("/users/login", json={"username": "u1", "password": "wrong"})
    assert r.status_code == 401


def test_history_limit_default_and_type(client: TestClient):
    _register(client, "dn", "u1", "pw123")
    auth = _auth_headers(client, "u1", "pw123")
    assert auth is not None
    bot = _create_bot(client, auth)
    bid = int(bot["id"])
    _send_bot(client, bid, "m1", auth_headers=auth)
    _send_bot(client, bid, "m2", auth_headers=auth)

    # explicit limit
    msgs = _history_bot(client, bid, limit=1, auth_headers=auth)
    assert isinstance(msgs, list)
    assert len(msgs) >= 1

    r = client.post("/chat/history/bot", json={"bot_id": bid, "limit": 50}, headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "messages" in body and isinstance(body["messages"], list)