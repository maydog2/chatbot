# tests/test_api_contract.py
from __future__ import annotations

from pathlib import Path
import pytest
import psycopg
from fastapi.testclient import TestClient

from companion.infra import db
from companion.api import app


# -------------------------
# Auth env (login requires AUTH_TOKEN_SECRET)
# -------------------------
@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test_secret_very_long_string")
    monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")


@pytest.fixture(autouse=True)
def _stub_llm_contract(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("companion.infra.llm.get_reply", lambda messages: "contract stub")


# -------------------------
# Reset DB per test (no need to know table names)
# -------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESET_SQL_PATH = PROJECT_ROOT / "src" / "companion" / "reset.sql"


def _reset_db() -> None:
    if not RESET_SQL_PATH.exists():
        raise RuntimeError(f"reset.sql not found at: {RESET_SQL_PATH}")

    if not getattr(db, "DB_URL", None):
        raise RuntimeError(
            "db.DB_URL is not set. Ensure conftest sets TEST_DB_URL -> db.DB_URL."
        )

    sql_text = RESET_SQL_PATH.read_text(encoding="utf-8")
    with psycopg.connect(db.DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql_text)
        conn.commit()


@pytest.fixture()
def client():
    _reset_db()
    with TestClient(app) as c:
        yield c
    _reset_db()


# -------------------------
# Helpers: API calls
# -------------------------
def _register(client: TestClient, display_name: str, username: str, password: str):
    return client.post(
        "/users/register",
        json={"display_name": display_name, "username": username, "password": password},
    )


def _login(client: TestClient, username: str, password: str):
    return client.post("/users/login", json={"username": username, "password": password})


def _auth_headers(client: TestClient, username: str, password: str) -> dict[str, str] | None:
    """Login and return Authorization header for protected endpoints."""
    r = _login(client, username, password)
    if r.status_code != 200:
        return None
    token = r.json().get("access_token")
    if not token:
        return None
    return {"Authorization": f"Bearer {token}"}


def _send_bot(
    client: TestClient,
    bot_id: int,
    content: str,
    *,
    auth_headers: dict[str, str] | None = None,
):
    headers = auth_headers or {}
    return client.post(
        "/chat/send-bot-message",
        json={
            "bot_id": bot_id,
            "content": content,
            "system_prompt": "",
            "trust_delta": 0,
            "resonance_delta": 0,
        },
        headers=headers,
    )


def _history_bot(
    client: TestClient,
    bot_id: int,
    limit: int = 50,
    *,
    auth_headers: dict[str, str] | None = None,
):
    headers = auth_headers or {}
    return client.post(
        "/chat/history/bot",
        json={"bot_id": bot_id, "limit": limit},
        headers=headers,
    )


# -------------------------
# 1) Transaction rollback test
# -------------------------
def test_send_rolls_back_when_second_create_message_throws(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    r = _register(client, "dn", "u1", "pw1")
    assert r.status_code == 200, r.text
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None
    rb = client.post(
        "/bots",
        json={"name": "b", "direction": "x", "primary_interest": "anime"},
        headers=auth,
    )
    assert rb.status_code == 200, rb.text

    orig = db.create_message
    n = {"c": 0}

    def _wrap(*args, **kwargs):
        n["c"] += 1
        if n["c"] >= 2:
            raise RuntimeError("forced failure after first message insert")
        return orig(*args, **kwargs)

    monkeypatch.setattr(db, "create_message", _wrap)

    bot_id = int(rb.json()["id"])
    with TestClient(app, raise_server_exceptions=False) as c:
        r = _send_bot(c, bot_id, "hello", auth_headers=auth)
        assert r.status_code >= 500, r.text

        r = _history_bot(c, bot_id, limit=50, auth_headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["messages"] == []


# -------------------------
# 2) Boundary / validation tests
# -------------------------
def test_register_missing_field_returns_422(client: TestClient):
    r = client.post("/users/register", json={"username": "u", "password": "p"})
    assert r.status_code == 422


def test_history_bot_missing_bot_id_returns_422(client: TestClient):
    _register(client, "dn", "u1", "pw1")
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None
    r = client.post("/chat/history/bot", json={"limit": 10}, headers=auth)
    assert r.status_code == 422


def test_history_bot_new_bot_returns_empty_messages(client: TestClient):
    r = _register(client, "dn", "u1", "pw1")
    assert r.status_code == 200, r.text
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None
    rb = client.post(
        "/bots",
        json={"name": "h", "direction": "x", "primary_interest": "anime"},
        headers=auth,
    )
    assert rb.status_code == 200, rb.text
    bot_id = int(rb.json()["id"])

    r = _history_bot(client, bot_id, limit=50, auth_headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["messages"] == []


# -------------------------
# 3) Idempotency tests
# -------------------------
def test_register_same_username_twice_returns_400(client: TestClient):
    r1 = _register(client, "dn1", "dup_user", "pw1")
    assert r1.status_code == 200, r1.text

    r2 = _register(client, "dn2", "dup_user", "pw2")
    # Your api.py maps ValueError to 400 for register
    assert r2.status_code == 400, r2.text

def test_login_wrong_password_returns_401_and_detail(client: TestClient):
    r = _register(client, "dn", "u1", "pw1")
    assert r.status_code == 200, r.text

    r = _login(client, "u1", "wrong")
    assert r.status_code == 401, r.text
    assert r.json().get("detail") == "invalid username or password"


def test_login_unknown_user_returns_401_and_detail(client: TestClient):
    r = _login(client, "no_such_user", "pw")
    assert r.status_code == 401, r.text
    assert r.json().get("detail") == "invalid username or password"


def test_register_returns_user_id_shape(client: TestClient):
    r = _register(client, "dn", "u1", "pw1")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "user_id" in body
    assert isinstance(body["user_id"], int)


def test_relationship_returns_shape(client: TestClient):
    r = _register(client, "dn", "u1", "pw1")
    assert r.status_code == 200, r.text
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None
    rb = client.post(
        "/bots",
        json={"name": "r", "direction": "x", "primary_interest": "anime"},
        headers=auth,
    )
    assert rb.status_code == 200, rb.text
    bot_id = int(rb.json()["id"])

    r = client.get(f"/bots/{bot_id}/relationship", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    for key in ("trust", "resonance", "affection", "openness", "mood", "display_name"):
        assert key in body
    assert isinstance(body["trust"], int)
    assert isinstance(body["resonance"], int)


def test_create_bot_rejects_duplicate_name_case_insensitive(client: TestClient):
    r = _register(client, "dn", "u1", "pw1")
    assert r.status_code == 200, r.text
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None
    r1 = client.post(
        "/bots",
        json={"name": "Emiya", "direction": "x", "primary_interest": "anime"},
        headers=auth,
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        "/bots",
        json={"name": "  emiya ", "direction": "y", "primary_interest": "gaming"},
        headers=auth,
    )
    assert r2.status_code == 400, r2.text
    assert "name" in (r2.json().get("detail") or "").lower()


def test_create_bot_rejects_duplicate_avatar_data_url(client: TestClient):
    r = _register(client, "dn", "u2", "pw2")
    assert r.status_code == 200, r.text
    auth = _auth_headers(client, "u2", "pw2")
    assert auth is not None
    data_url = "data:image/png;base64,TESTDUPLICATEAVATAR=="
    r1 = client.post(
        "/bots",
        json={
            "name": "Bot A",
            "direction": "x",
            "primary_interest": "anime",
            "avatar_data_url": data_url,
        },
        headers=auth,
    )
    assert r1.status_code == 200, r1.text
    r2 = client.post(
        "/bots",
        json={
            "name": "Bot B",
            "direction": "y",
            "primary_interest": "anime",
            "avatar_data_url": data_url,
        },
        headers=auth,
    )
    assert r2.status_code == 400, r2.text
    assert "avatar" in (r2.json().get("detail") or "").lower()