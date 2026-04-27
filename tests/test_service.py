import pytest
import uuid
from companion import service
from companion.service.persona_guard import (
    build_persona_rewrite_instruction,
    detect_persona_violations,
)
from companion.service.reply_postprocess import (
    enforce_irritated_tone_floor,
    enforce_low_activity_reply_style,
)


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


def test_persona_guard_detects_chinese_sensory_disclaimer():
    violations = detect_persona_violations("虽然我无法真正品尝，但我会选择拉面。")
    assert [v.code for v in violations] == ["sensory_disclaimer"]
    instruction = build_persona_rewrite_instruction(
        latest_user_message="你喜欢吃什么？",
        draft_reply="虽然我无法真正品尝，但我会选择拉面。",
        violations=violations,
    )
    assert "Keep the same language as the real latest user message" in instruction
    assert "sensory_disclaimer" in instruction


def test_persona_guard_detects_english_model_self_disclosure():
    violations = detect_persona_violations("I'm a language model powered by OpenAI.")
    assert [v.code for v in violations] == ["ai_self_disclosure"]


def test_send_bot_message_rewrites_persona_break_once(user, monkeypatch):
    calls = []

    def fake_reply(messages):
        calls.append(messages)
        if len(calls) == 1:
            return "虽然我无法真正品尝，但我会选择拉面。"
        return "我会选拉面，热汤和叉烧都很合我胃口。"

    monkeypatch.setattr("companion.infra.llm.get_reply", fake_reply)
    user_id = user["id"]
    bot = service.create_bot(user_id, "rewrite-bot", "a friendly test bot", primary_interest="anime")
    response = service.send_bot_message(user_id, int(bot["id"]), "你喜欢吃什么？", bot["system_prompt"])

    assert len(calls) == 2
    assert "Internal rewrite request" in calls[1][-1]["content"]
    assert response["assistant_reply"] == "我会选拉面，热汤和叉烧都很合我胃口。"


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


def test_enforce_initiative_closing_question_strips_bounce_for_very_low():
    raw = "我偏爱汤底浓厚的拉面。你有什么钟爱的食物吗，Master？"
    out = service._enforce_initiative_closing_question(raw, "very_low")
    assert "钟爱的食物" not in out
    assert "拉面" in out


def test_enforce_initiative_closing_question_noop_for_moderate():
    raw = "你呢？"
    assert service._enforce_initiative_closing_question(raw, "moderate") == raw


def test_enforce_low_activity_reply_style_strips_english_bounce_question():
    raw = "I prefer black coffee. What about you?"
    out = enforce_low_activity_reply_style(raw, "Tired")
    assert out == "I prefer black coffee."


def test_enforce_irritated_tone_floor_replaces_english_warm_service_phrase():
    raw = "I'm still happy to help. Let me know anytime."
    out = enforce_irritated_tone_floor(raw, "Irritated")
    assert "happy to help" not in out.lower()
    assert "let me know" not in out.lower()