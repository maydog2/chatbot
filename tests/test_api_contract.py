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


def _send_bot_ephemeral_gomoku(
    client: TestClient,
    bot_id: int,
    content: str,
    *,
    auth_headers: dict[str, str] | None = None,
    relationship_events: list[str] | None = None,
    position_summary: dict | None = None,
):
    headers = auth_headers or {}
    eph: dict = {
        "active_game": {
            "type": "gomoku",
            "difficulty": "serious",
            "current_turn": "user",
            "bot_side": "white",
        },
        "game_messages": [],
    }
    if relationship_events:
        eph["relationship_events"] = relationship_events
    if position_summary:
        eph["position_summary"] = position_summary
    return client.post(
        "/chat/send-bot-message",
        json={
            "bot_id": bot_id,
            "content": content,
            "system_prompt": "",
            "trust_delta": 0,
            "resonance_delta": 0,
            "ephemeral_game": eph,
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
    bot_id = int(rb.json()["id"])

    rel_before_res = client.get(f"/bots/{bot_id}/relationship", headers=auth)
    assert rel_before_res.status_code == 200, rel_before_res.text
    rel_before = rel_before_res.json()
    rel_snapshot_before = (
        rel_before["trust"],
        rel_before["resonance"],
        rel_before["affection"],
        rel_before["openness"],
        rel_before["mood"],
    )

    orig = db.create_message
    n = {"c": 0}

    def _wrap(*args, **kwargs):
        n["c"] += 1
        if n["c"] >= 2:
            raise RuntimeError("forced failure after first message insert")
        return orig(*args, **kwargs)

    monkeypatch.setattr(db, "create_message", _wrap)

    with TestClient(app, raise_server_exceptions=False) as c:
        r = _send_bot(c, bot_id, "hello", auth_headers=auth)
        assert r.status_code == 503, r.text
        assert r.json().get("detail") == "forced failure after first message insert"

        r = _history_bot(c, bot_id, limit=50, auth_headers=auth)
        assert r.status_code == 200, r.text
        assert r.json()["messages"] == []

        rel_after_fail_res = c.get(f"/bots/{bot_id}/relationship", headers=auth)
        assert rel_after_fail_res.status_code == 200, rel_after_fail_res.text
        rel_after_fail = rel_after_fail_res.json()
        rel_snapshot_after_fail = (
            rel_after_fail["trust"],
            rel_after_fail["resonance"],
            rel_after_fail["affection"],
            rel_after_fail["openness"],
            rel_after_fail["mood"],
        )
        assert rel_snapshot_after_fail == rel_snapshot_before

        monkeypatch.setattr(db, "create_message", orig)
        ok = _send_bot(c, bot_id, "hello after fail", auth_headers=auth)
        assert ok.status_code == 200, ok.text

        r = _history_bot(c, bot_id, limit=50, auth_headers=auth)
        assert r.status_code == 200, r.text
        msgs = r.json()["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant"]
        assert [m["content"] for m in msgs] == ["hello after fail", "contract stub"]


# -------------------------
# 2) Boundary / validation tests
# -------------------------
def test_register_missing_field_returns_422(client: TestClient):
    r = client.post("/users/register", json={"username": "u", "password": "p"})
    assert r.status_code == 422
    assert any("display_name" in err.get("loc", []) for err in r.json().get("detail", []))


def test_history_bot_missing_bot_id_returns_422(client: TestClient):
    _register(client, "dn", "u1", "pw1")
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None
    r = client.post("/chat/history/bot", json={"limit": 10}, headers=auth)
    assert r.status_code == 422
    assert any("bot_id" in err.get("loc", []) for err in r.json().get("detail", []))


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/users/me", None),
        ("patch", "/users/me", {"display_name": "x"}),
        ("get", "/bots", None),
        ("post", "/bots", {"name": "b", "direction": "x", "primary_interest": "anime"}),
        ("get", "/bots/1/relationship", None),
        ("patch", "/bots/1", {"name": "new_name"}),
        ("delete", "/bots/1", None),
        (
            "post",
            "/chat/send-bot-message",
            {"bot_id": 1, "content": "hello", "system_prompt": "", "trust_delta": 0, "resonance_delta": 0},
        ),
        ("post", "/chat/history/bot", {"bot_id": 1, "limit": 10}),
        ("post", "/chat/end", None),
        (
            "post",
            "/games/gomoku/relationship-events",
            {"bot_id": 1, "relationship_events": ["user_win"]},
        ),
    ],
)
def test_protected_endpoints_reject_missing_or_invalid_bearer(
    client: TestClient, method: str, path: str, json_body: dict | None
):
    # Missing bearer token should be rejected consistently.
    no_auth_res = client.request(method.upper(), path, json=json_body)
    assert no_auth_res.status_code == 401, no_auth_res.text
    assert no_auth_res.json().get("detail") == "missing bearer token"

    # Malformed/invalid bearer token should also be rejected.
    bad_auth_res = client.request(
        method.upper(), path, json=json_body, headers={"Authorization": "Bearer not_a_real_token"}
    )
    assert bad_auth_res.status_code == 401, bad_auth_res.text


def test_bot_scoped_routes_return_404_for_unknown_bot(client: TestClient):
    _register(client, "dn", "u1", "pw1")
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None

    r = _history_bot(client, 999, limit=50, auth_headers=auth)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"

    r = _send_bot(client, 999, "hello", auth_headers=auth)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"

    r = client.get("/bots/999/relationship", headers=auth)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"

    r = client.post(
        "/games/gomoku/relationship-events",
        json={"bot_id": 999, "relationship_events": ["user_win"]},
        headers=auth,
    )
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"


def test_bot_chat_routes_enforce_cross_user_isolation(client: TestClient):
    # User A owns the bot.
    ra = _register(client, "dn_a", "user_a", "pw_a")
    assert ra.status_code == 200, ra.text
    auth_a = _auth_headers(client, "user_a", "pw_a")
    assert auth_a is not None
    rb = client.post(
        "/bots",
        json={"name": "a_bot", "direction": "x", "primary_interest": "anime"},
        headers=auth_a,
    )
    assert rb.status_code == 200, rb.text
    bot_id = int(rb.json()["id"])

    # User B is authenticated but should not access User A's bot.
    rb2 = _register(client, "dn_b", "user_b", "pw_b")
    assert rb2.status_code == 200, rb2.text
    auth_b = _auth_headers(client, "user_b", "pw_b")
    assert auth_b is not None

    r = client.get(f"/bots/{bot_id}/relationship", headers=auth_b)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"

    r = client.patch(f"/bots/{bot_id}", json={"name": "hacked_name"}, headers=auth_b)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"

    r = client.delete(f"/bots/{bot_id}", headers=auth_b)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"

    r = _send_bot(client, bot_id, "hello", auth_headers=auth_b)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"

    r = _history_bot(client, bot_id, limit=10, auth_headers=auth_b)
    assert r.status_code == 404, r.text
    assert r.json().get("detail") == "bot not found"


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


def test_history_bot_respects_limit_window(client: TestClient):
    r = _register(client, "dn", "u_hist", "pw_hist")
    assert r.status_code == 200, r.text
    auth = _auth_headers(client, "u_hist", "pw_hist")
    assert auth is not None
    rb = client.post(
        "/bots",
        json={"name": "hist_bot", "direction": "x", "primary_interest": "anime"},
        headers=auth,
    )
    assert rb.status_code == 200, rb.text
    bot_id = int(rb.json()["id"])

    r1 = _send_bot(client, bot_id, "m1", auth_headers=auth)
    assert r1.status_code == 200, r1.text
    r2 = _send_bot(client, bot_id, "m2", auth_headers=auth)
    assert r2.status_code == 200, r2.text

    r = _history_bot(client, bot_id, limit=1, auth_headers=auth)
    assert r.status_code == 200, r.text
    msgs1 = r.json()["messages"]
    assert len(msgs1) == 1
    assert msgs1[0]["role"] == "assistant"
    assert msgs1[0]["content"] == "contract stub"

    r = _history_bot(client, bot_id, limit=50, auth_headers=auth)
    assert r.status_code == 200, r.text
    msgs_all = r.json()["messages"]
    assert [m["role"] for m in msgs_all] == ["user", "assistant", "user", "assistant"]
    assert [m["content"] for m in msgs_all] == ["m1", "contract stub", "m2", "contract stub"]


# -------------------------
# 4) Gomoku relationship events (ephemeral)
# -------------------------
def test_gomoku_relationship_events_apply_to_stats_and_mood(client: TestClient):
    r = _register(client, "dn", "u1", "pw1")
    assert r.status_code == 200, r.text
    auth = _auth_headers(client, "u1", "pw1")
    assert auth is not None
    rb = client.post(
        "/bots",
        json={"name": "g", "direction": "x", "primary_interest": "anime"},
        headers=auth,
    )
    assert rb.status_code == 200, rb.text
    bot_id = int(rb.json()["id"])

    # Baseline relationship for a new bot is (40,30,40,30,"Calm") per service.create_bot.
    r1 = _send_bot_ephemeral_gomoku(
        client,
        bot_id,
        "gg",
        auth_headers=auth,
        relationship_events=["user_win"],
        position_summary={
            "phase": "endgame",
            "eval": "even",
            "urgency": "none",
            "move_count": 12,
            "last_move": None,
            "last_move_by": None,
            "current_turn": "user",
            "game_over": True,
            "match_result": "user_win",
            "threats": {"user": [], "bot": []},
            "winning_points": {"user": [], "bot": []},
            "events": [],
        },
    )
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["trust"] == 41
    assert body["resonance"] == 31
    assert body["mood"] in ("Playful", "Happy", "Calm", "Quiet", "Tired", "Irritated")
    assert body["mood"] == "Playful"

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
    for key in ("trust", "resonance", "affection", "openness"):
        assert isinstance(body[key], int)
        assert 0 <= body[key] <= 100
    assert isinstance(body["mood"], str)
    assert body["display_name"] == "dn"


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


def test_patch_bot_personality_only_persists(client: TestClient):
    """PATCH with only personality must update game reply style (partial body)."""
    _register(client, "dn", "u_pers", "pw_pers")
    auth = _auth_headers(client, "u_pers", "pw_pers")
    assert auth is not None
    rb = client.post(
        "/bots",
        json={"name": "sty", "direction": "x", "primary_interest": "anime"},
        headers=auth,
    )
    assert rb.status_code == 200, rb.text
    bot_id = int(rb.json()["id"])
    assert rb.json().get("personality") == "gentle"

    rp = client.patch(
        f"/bots/{bot_id}",
        json={"personality": "cool"},
        headers=auth,
    )
    assert rp.status_code == 200, rp.text
    assert rp.json().get("personality") == "cool"

    rlist = client.get("/bots", headers=auth)
    assert rlist.status_code == 200, rlist.text
    row = next(b for b in rlist.json()["bots"] if b["id"] == bot_id)
    assert row.get("personality") == "cool"