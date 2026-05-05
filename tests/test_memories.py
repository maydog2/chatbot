from __future__ import annotations

import math
import uuid

from fastapi.testclient import TestClient
import psycopg
import pytest

from companion import service
from companion.api import app
from companion.infra import db
from companion.service.memory_extraction import parse_memory_candidates


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture
def memory_user():
    user_id = db.create_user(_uniq("dn"), _uniq("mem_u"), "Abcdefg123!@#")
    try:
        yield user_id
    finally:
        try:
            db.delete_user(user_id)
        except Exception:
            pass


def _bot_for_user(user_id: int) -> dict:
    return service.create_bot(user_id, _uniq("mem_bot"), "a memory test bot", primary_interest="anime")


def test_memory_repository_create_list_update_and_deactivate(memory_user):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Please remember I like concise replies.")

    memory_id = db.create_memory(
        memory_user,
        sid,
        mid,
        "User prefers concise replies.",
        "preference",
        importance=75,
        embedding=[0.1, 0.2, 0.3],
    )

    memories = db.list_active_memories(memory_user, limit=10)
    assert [m["id"] for m in memories] == [memory_id]
    assert memories[0]["content"] == "User prefers concise replies."
    assert memories[0]["embedding"] == "[0.1,0.2,0.3]"

    assert db.update_memory(memory_id, importance=90)
    assert db.list_active_memories(memory_user, limit=1)[0]["importance"] == 90

    assert db.deactivate_memory(memory_id)
    assert db.list_active_memories(memory_user, limit=10) == []


def test_memory_repository_enforces_active_and_total_limits(memory_user):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember several things.")
    for i in range(6):
        db.create_memory(
            memory_user,
            sid,
            mid,
            f"User memory {i}.",
            "background",
            importance=10 + i,
        )

    stats = db.enforce_memory_limits(memory_user, active_limit=3, total_limit=4)

    assert stats == {"deactivated": 3, "deleted": 2}
    active = db.list_active_memories(memory_user, limit=10)
    assert len(active) == 3
    assert [m["importance"] for m in active] == [15, 14, 13]

    with psycopg.connect(db.DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), count(*) FILTER (WHERE is_active) FROM memories WHERE user_id = %s",
                (memory_user,),
            )
            total_count, active_count = cur.fetchone()
    assert total_count == 4
    assert active_count == 3


def test_memory_repository_rejects_invalid_values(memory_user):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "hello")

    with pytest.raises(ValueError, match="content must be non-empty"):
        db.create_memory(memory_user, sid, mid, "   ", "preference")

    with pytest.raises(ValueError, match="invalid memory_type"):
        db.create_memory(memory_user, sid, mid, "User likes tea.", "temporary")

    with pytest.raises(ValueError, match="importance"):
        db.create_memory(memory_user, sid, mid, "User likes tea.", "preference", importance=101)


def test_memory_repository_rejects_non_finite_embedding_values(memory_user):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "hello")

    with pytest.raises(ValueError, match="finite numbers"):
        db.create_memory(memory_user, sid, mid, "User likes tea.", "preference", embedding=[math.nan])

    with pytest.raises(ValueError, match="finite numbers"):
        db.create_memory(memory_user, sid, mid, "User likes tea.", "preference", embedding=[math.inf])

    with pytest.raises(ValueError, match="finite numbers"):
        db.create_memory(memory_user, sid, mid, "User likes tea.", "preference", embedding=[-math.inf])


def test_memory_repository_rejects_missing_foreign_keys(memory_user):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "hello")

    with pytest.raises(ValueError, match="not found"):
        db.create_memory(memory_user + 999999, sid, mid, "User likes tea.", "preference")

    with pytest.raises(ValueError, match="not found"):
        db.create_memory(memory_user, sid + 999999, mid, "User likes tea.", "preference")

    with pytest.raises(ValueError, match="not found"):
        db.create_memory(memory_user, sid, mid + 999999, "User likes tea.", "preference")


def test_update_memory_rejects_invalid_values(memory_user):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "hello")
    memory_id = db.create_memory(memory_user, sid, mid, "User likes tea.", "preference")

    with pytest.raises(ValueError, match="content must be non-empty"):
        db.update_memory(memory_id, content="   ")

    with pytest.raises(ValueError, match="invalid memory_type"):
        db.update_memory(memory_id, memory_type="temporary")

    with pytest.raises(ValueError, match="importance"):
        db.update_memory(memory_id, importance=101)


def test_parse_memory_candidates_handles_fenced_json_and_filters_bad_items():
    raw = """```json
    {
      "memories": [
        {"content": "User prefers concise replies.", "memory_type": "preference", "importance": 80},
        {"content": "", "memory_type": "preference", "importance": 80},
        {"content": "A one-off item", "memory_type": "temporary", "importance": 50},
        {"content": "User prefers concise replies.", "memory_type": "preference", "importance": 80}
      ]
    }
    ```"""

    candidates = parse_memory_candidates(raw)

    assert len(candidates) == 1
    assert candidates[0].content == "User prefers concise replies."
    assert candidates[0].memory_type == "preference"
    assert candidates[0].importance == 80
    assert parse_memory_candidates("not json") == []


def test_memory_pipeline_saves_candidates_and_dedupes(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember that I prefer concise replies.")
    db.create_message(memory_user, sid, "assistant", "Got it.")

    monkeypatch.setattr(
        "companion.infra.llm.extract_memories_json",
        lambda **kwargs: '{"memories":[{"content":"User prefers concise replies.",'
        '"memory_type":"preference","importance":70}]}',
    )
    monkeypatch.setattr("companion.infra.llm.get_embedding", lambda text: [0.4, 0.5])

    service.run_memory_pipeline_for_turn(
        user_id=memory_user,
        session_id=sid,
        source_message_id=mid,
        user_message="Remember that I prefer concise replies.",
        assistant_response="Got it.",
    )
    service.run_memory_pipeline_for_turn(
        user_id=memory_user,
        session_id=sid,
        source_message_id=mid,
        user_message="Remember that I prefer concise replies.",
        assistant_response="Got it.",
    )

    memories = db.list_active_memories(memory_user, limit=10)
    assert len(memories) == 1
    assert memories[0]["content"] == "User prefers concise replies."
    assert memories[0]["embedding"] == "[0.4,0.5]"


def test_memory_pipeline_dedupes_semantically_similar_memory(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    old_mid = db.create_message(memory_user, sid, "user", "I like sushi.")
    old_id = db.create_memory(
        memory_user,
        sid,
        old_mid,
        "User likes sushi.",
        "preference",
        importance=60,
        embedding=[1.0, 0.0],
    )
    new_mid = db.create_message(memory_user, sid, "user", "Remember that I like to eat sushi.")

    monkeypatch.setattr(
        "companion.infra.llm.extract_memories_json",
        lambda **kwargs: '{"memories":[{"content":"User likes to eat sushi.",'
        '"memory_type":"preference","importance":75}]}',
    )
    monkeypatch.setattr("companion.infra.llm.get_embedding", lambda text: [0.99, 0.01])

    service.run_memory_pipeline_for_turn(
        user_id=memory_user,
        session_id=sid,
        source_message_id=new_mid,
        user_message="Remember that I like to eat sushi.",
        assistant_response="Got it.",
    )

    memories = db.list_active_memories(memory_user, limit=10)
    assert len(memories) == 1
    assert int(memories[0]["id"]) == int(old_id)
    assert memories[0]["content"] == "User likes sushi."
    assert memories[0]["importance"] == 75
    assert memories[0]["embedding"] == "[0.99,0.01]"


def test_memory_pipeline_replacement_deactivates_old_memory(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    old_mid = db.create_message(memory_user, sid, "user", "I like hot coffee.")
    old_id = db.create_memory(
        memory_user,
        sid,
        old_mid,
        "User prefers hot coffee.",
        "preference",
        importance=60,
    )
    new_mid = db.create_message(memory_user, sid, "user", "Actually I prefer tea now.")

    monkeypatch.setattr(
        "companion.infra.llm.extract_memories_json",
        lambda **kwargs: '{"memories":[{"content":"User now prefers tea rather than coffee.",'
        '"memory_type":"preference","importance":75}]}',
    )
    def embedding_for_text(text):
        if "tea" in text:
            return [0.0, 1.0]
        return [1.0, 0.0]

    monkeypatch.setattr("companion.infra.llm.get_embedding", embedding_for_text)

    service.run_memory_pipeline_for_turn(
        user_id=memory_user,
        session_id=sid,
        source_message_id=new_mid,
        user_message="Actually I prefer tea now.",
        assistant_response="Got it.",
    )

    active = db.list_active_memories(memory_user, limit=10)
    assert len(active) == 1
    assert active[0]["content"] == "User now prefers tea rather than coffee."

    old_row = db.find_active_memories_for_dedupe(memory_user)
    assert all(int(m["id"]) != int(old_id) for m in old_row)


def test_memory_pipeline_does_not_reuse_deactivated_memory_in_same_batch(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    old_mid = db.create_message(memory_user, sid, "user", "I like hot coffee.")
    old_id = db.create_memory(
        memory_user,
        sid,
        old_mid,
        "User prefers hot coffee.",
        "preference",
        importance=60,
        embedding=[1.0, 0.0],
    )
    new_mid = db.create_message(memory_user, sid, "user", "Actually I prefer tea now.")

    monkeypatch.setattr(
        "companion.infra.llm.extract_memories_json",
        lambda **kwargs: '{"memories":['
        '{"content":"User now prefers tea rather than coffee.",'
        '"memory_type":"preference","importance":75},'
        '{"content":"User prefers hot coffee.",'
        '"memory_type":"preference","importance":65}'
        "]}",
    )
    def embedding_for_text(text):
        if "tea" in text:
            return [0.0, 1.0]
        return [1.0, 0.0]

    monkeypatch.setattr("companion.infra.llm.get_embedding", embedding_for_text)

    service.run_memory_pipeline_for_turn(
        user_id=memory_user,
        session_id=sid,
        source_message_id=new_mid,
        user_message="Actually I prefer tea now.",
        assistant_response="Got it.",
    )

    active = db.list_active_memories(memory_user, limit=10)
    active_contents = {memory["content"] for memory in active}
    assert int(old_id) not in {int(memory["id"]) for memory in active}
    assert "User now prefers tea rather than coffee." in active_contents
    assert "User prefers hot coffee." in active_contents


def test_memory_pipeline_failures_do_not_raise(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember this.")

    def boom(**kwargs):
        raise RuntimeError("extractor unavailable")

    monkeypatch.setattr("companion.infra.llm.extract_memories_json", boom)

    service.run_memory_pipeline_for_turn(
        user_id=memory_user,
        session_id=sid,
        source_message_id=mid,
        user_message="Remember this.",
        assistant_response="OK.",
    )

    assert db.list_active_memories(memory_user, limit=10) == []


def test_send_bot_message_includes_active_memories_in_prompt(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember that I like jasmine tea.")
    db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes jasmine tea.",
        "preference",
        importance=70,
    )
    captured = {}

    def fake_reply(messages):
        captured["system"] = messages[0]["content"]
        return "stub reply"

    monkeypatch.setattr("companion.infra.llm.get_reply", fake_reply)
    monkeypatch.setattr("companion.infra.llm.get_embedding", lambda text: [0.1, 0.2])

    service.send_bot_message(memory_user, int(bot["id"]), "What tea do I like?", bot["system_prompt"])

    assert "Relevant long-term context about the user" in captured["system"]
    assert "User likes jasmine tea." in captured["system"]
    assert "Do not explicitly mention these notes" in captured["system"]


def test_send_bot_message_without_memories_omits_memory_prompt_block(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    captured = {}

    def fake_reply(messages):
        captured["system"] = messages[0]["content"]
        return "stub reply"

    monkeypatch.setattr("companion.infra.llm.get_reply", fake_reply)

    service.send_bot_message(memory_user, int(bot["id"]), "Hello.", bot["system_prompt"])

    assert "Relevant long-term context about the user" not in captured["system"]


def test_build_memory_prompt_block_formats_retrieved_memories_without_db():
    block = service.build_memory_prompt_block(
        [
            {"content": "User prefers concise replies."},
            {"content": "User likes jasmine tea."},
        ],
        line_char_limit=40,
    )

    assert block.startswith("Relevant long-term context about the user:")
    assert "- User prefers concise replies." in block
    assert "- User likes jasmine tea." in block
    assert "Use this context only when relevant to the current reply." in block


def test_retrieve_prompt_memories_uses_query_embedding_similarity(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember several preferences.")
    db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes jasmine tea.",
        "preference",
        importance=20,
        embedding=[1.0, 0.0],
    )
    db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes video games.",
        "preference",
        importance=90,
        embedding=[0.0, 1.0],
    )
    monkeypatch.setattr("companion.infra.llm.get_embedding", lambda text: [1.0, 0.0])
    monkeypatch.setattr(
        "companion.service.memory_extraction._cosine_similarity",
        lambda left, right: (_ for _ in ()).throw(AssertionError("Python cosine should not run")),
    )

    memories = service.retrieve_prompt_memories_for_user(memory_user, query="What tea do I like?", limit=1)

    assert len(memories) == 1
    assert memories[0]["content"] == "User likes jasmine tea."
    assert "distance" in memories[0]
    assert "similarity" not in memories[0]
    assert "embedding" not in memories[0]


def test_retrieve_prompt_memories_falls_back_when_memories_have_no_embedding(
    memory_user,
    monkeypatch,
):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember my tea preferences.")
    db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes jasmine tea.",
        "preference",
        importance=70,
    )
    monkeypatch.setattr("companion.infra.llm.get_embedding", lambda text: [1.0, 0.0])

    memories = service.retrieve_prompt_memories_for_user(memory_user, query="What tea do I like?", limit=1)

    assert len(memories) == 1
    assert memories[0]["content"] == "User likes jasmine tea."


def test_retrieve_prompt_memories_tiebreaks_by_updated_at(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember several preferences.")
    older_id = db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes older tea.",
        "preference",
        importance=70,
        embedding=[1.0, 0.0],
    )
    newer_id = db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes newer tea.",
        "preference",
        importance=70,
        embedding=[1.0, 0.0],
    )
    assert db.update_memory(older_id, source_message_id=mid)
    assert db.update_memory(newer_id, source_message_id=mid)
    monkeypatch.setattr("companion.infra.llm.get_embedding", lambda text: [1.0, 0.0])

    memories = service.retrieve_prompt_memories_for_user(memory_user, query="What tea do I like?", limit=1)

    assert len(memories) == 1
    assert int(memories[0]["id"]) == int(newer_id)


def test_memory_prompt_block_omits_inactive_memories(memory_user):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember my tea preferences.")
    active_id = db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes jasmine tea.",
        "preference",
        importance=70,
    )
    inactive_id = db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes stale tea.",
        "preference",
        importance=90,
    )
    assert active_id != inactive_id
    assert db.deactivate_memory(inactive_id)

    block = service.memory_prompt_block_for_user(memory_user)

    assert "User likes jasmine tea." in block
    assert "User likes stale tea." not in block


def test_memory_prompt_block_uses_env_limit_and_truncates_lines(memory_user, monkeypatch):
    bot = _bot_for_user(memory_user)
    sid = int(bot["session_id"])
    mid = db.create_message(memory_user, sid, "user", "Remember my preferences.")
    db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes very long jasmine tea descriptions that should be shortened.",
        "preference",
        importance=90,
    )
    db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes oolong tea.",
        "preference",
        importance=80,
    )
    db.create_memory(
        memory_user,
        sid,
        mid,
        "User likes mint tea.",
        "preference",
        importance=70,
    )
    monkeypatch.setenv("CHATBOT_PROMPT_MEMORY_LIMIT", "2")
    monkeypatch.setenv("CHATBOT_PROMPT_MEMORY_LINE_CHAR_LIMIT", "32")

    block = service.memory_prompt_block_for_user(memory_user)

    assert "User likes very long jasmine..." in block
    assert "User likes oolong tea." in block
    assert "User likes mint tea." not in block

    monkeypatch.setenv("CHATBOT_PROMPT_MEMORY_LIMIT", "0")
    assert service.memory_prompt_block_for_user(memory_user) == ""


def test_send_bot_message_background_task_stores_memory(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test_secret_very_long_string")
    monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")
    monkeypatch.setattr("companion.infra.llm.get_reply", lambda messages: "api reply")
    monkeypatch.setattr(
        "companion.infra.llm.extract_memories_json",
        lambda **kwargs: '{"memories":[{"content":"User likes jasmine tea.",'
        '"memory_type":"preference","importance":65}]}',
    )
    monkeypatch.setattr("companion.infra.llm.get_embedding", lambda text: [0.7, 0.8])

    with TestClient(app) as client:
        username = _uniq("api_mem_u")
        password = "Abcdefg123!@#"
        register = client.post(
            "/users/register",
            json={"display_name": "Memory User", "username": username, "password": password},
        )
        assert register.status_code == 200, register.text
        user_id = int(register.json()["user_id"])
        token = client.post("/users/login", json={"username": username, "password": password}).json()[
            "access_token"
        ]
        headers = {"Authorization": f"Bearer {token}"}
        bot = client.post(
            "/bots",
            json={"name": _uniq("api_mem_bot"), "direction": "test bot", "primary_interest": "anime"},
            headers=headers,
        )
        assert bot.status_code == 200, bot.text
        response = client.post(
            "/chat/send-bot-message",
            json={"bot_id": int(bot.json()["id"]), "content": "I like jasmine tea.", "system_prompt": ""},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["assistant_reply"] == "api reply"

    memories = db.list_active_memories(user_id, limit=10)
    assert len(memories) == 1
    assert memories[0]["content"] == "User likes jasmine tea."
    assert memories[0]["embedding"] == "[0.7,0.8]"
