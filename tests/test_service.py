import pytest
import uuid
from companion import service


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test_secret_very_long_string")
    monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")


def test_login_success_and_failure(user):
    assert service.login(user["username"], user["password"]) == user["id"]
    with pytest.raises(ValueError, match="invalid username or password"):
        service.login(user["username"], "wrong_password")


@pytest.fixture
def stub_llm(monkeypatch):
    monkeypatch.setattr("companion.infra.llm.get_reply", lambda messages: "stub reply")


def test_send_bot_message_persists_user_and_assistant(user, stub_llm):
    user_id = user["id"]
    bot = service.create_bot(user_id, "t", "a friendly test bot", primary_interest="anime")
    bid = int(bot["id"])
    sid = int(bot["session_id"])

    response = service.send_bot_message(user_id, bid, "Hello, world!", bot["system_prompt"])
    assert isinstance(response["session_id"], int)
    assert isinstance(response["message_id"], int)
    assert response["session_id"] == sid

    history = service.get_history_for_bot(user_id, bid, limit=10)
    assert len(history) == 2
    assert history[0]["id"] == response["message_id"]
    assert history[0]["content"] == "Hello, world!"
    assert history[0]["role"] == "user"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "stub reply"


def test_end_current_session(user):
    user_id = user["id"]
    service.ensure_active_session(user_id)
    assert service.end_current_session(user_id) is True
    assert service.end_current_session(user_id) is False


def test_get_relationship_returns_bounds(user):
    trust, resonance = service.get_relationship(user["id"])
    assert isinstance(trust, int)
    assert isinstance(resonance, int)
    assert 0 <= trust <= 100
    assert 0 <= resonance <= 100


def test_register_user_creates_relationship():
    username = f"svc_test_{uuid.uuid4().hex[:10]}"
    user_id = service.register_user("svc_dn", username, "Abcdefg123!@#")
    trust, resonance = service.get_relationship(user_id)
    assert 0 <= trust <= 100
    assert 0 <= resonance <= 100


def test_ensure_active_session_reuses_active_session(user):
    user_id = user["id"]

    sid1 = service.ensure_active_session(user_id)
    sid2 = service.ensure_active_session(user_id)
    assert sid2 == sid1

    assert service.end_current_session(user_id) is True
    sid3 = service.ensure_active_session(user_id)
    assert sid3 != sid1


def test_send_and_get_history_includes_latest_message(user, stub_llm):
    user_id = user["id"]
    bid = int(
        service.create_bot(user_id, "hbot", "history test bot", primary_interest="anime")["id"]
    )

    res1 = service.send_and_get_history(user_id, bid, "Hello", limit=10)
    assert [m["content"] for m in res1["history"]] == ["Hello", "stub reply"]

    res2 = service.send_and_get_history(user_id, bid, "World", limit=10)
    assert [m["content"] for m in res2["history"]] == [
        "Hello",
        "stub reply",
        "World",
        "stub reply",
    ]

    res3 = service.send_and_get_history(user_id, bid, "!", limit=2)
    assert [m["content"] for m in res3["history"]] == ["!", "stub reply"]


def test_issue_access_token_success_and_token_can_be_used(user, auth_env):
    # user fixture gives {"id","username","password",...}; auth_env sets AUTH_TOKEN_SECRET
    res = service.issue_access_token(user["username"], user["password"])
    assert "access_token" in res
    assert res["token_type"] == "bearer"
    assert "expires_at" in res

    uid = service.get_user_id_from_token(res["access_token"])
    assert uid == user["id"]


def test_issue_access_token_wrong_password_raises(user):
    with pytest.raises(ValueError):
        service.issue_access_token(user["username"], "wrong_pw")


def test_get_user_id_from_token_invalid_raises(auth_env):
    with pytest.raises(ValueError):
        service.get_user_id_from_token("this_is_not_a_real_token")


def test_strip_roleplay_sensory_disclaimers_removes_chinese_taste_opening():
    raw = "虽然不能实际品尝食物，但我会对那些料理感兴趣。"
    out = service._strip_roleplay_sensory_disclaimers(raw)
    assert "品尝" not in out
    assert "料理" in out


def test_strip_conditional_taste_opening_and_meta_sentence():
    raw = (
        "如果能品尝，我可能会对充满风味的料理情有独钟，像是日式拉面。"
        "美食的多样性和复杂的风味总是令人着迷。"
    )
    out = service._strip_roleplay_sensory_disclaimers(raw)
    assert "如果能" not in out
    assert "着迷" not in out
    assert "拉面" in out


def test_strip_imagination_taste_clause_and_trailing_meta():
    raw = "虽然无法真正品尝，但在想象中，我会偏爱拉面。它们总能在想象中引发无限的味觉遐想。"
    out = service._strip_roleplay_sensory_disclaimers(raw)
    assert "无法真正品尝" not in out
    assert "味觉遐想" not in out
    assert "想象中引发" not in out
    assert "拉面" in out


def test_enforce_initiative_closing_question_strips_bounce_for_very_low():
    raw = "我偏爱汤底浓厚的拉面。你有什么钟爱的食物吗，Master？"
    out = service._enforce_initiative_closing_question(raw, "very_low")
    assert "钟爱的食物" not in out
    assert "拉面" in out


def test_enforce_initiative_closing_question_noop_for_moderate():
    raw = "你呢？"
    assert service._enforce_initiative_closing_question(raw, "moderate") == raw