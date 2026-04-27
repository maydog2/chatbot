"""Tests for user-content token budgeting before the main chat completion."""

import pytest

from companion.infra import message_token_budget as mtb


class _FakeEnc:
    """1 token per character for predictable trimming."""

    def encode(self, s: str) -> list[int]:
        return [0] * len(s or "")

    def decode(self, toks: list[int]) -> str:
        return "x" * len(toks)


@pytest.fixture
def fake_enc(monkeypatch):
    monkeypatch.setattr(mtb, "_budget_encoder", _FakeEnc())


def test_budget_zero_returns_full_copy(fake_enc):
    msgs = [{"role": "user", "content": "ab"}]
    out = mtb.clip_openai_messages_by_user_token_budget(msgs, 0)
    assert out == msgs
    assert out is not msgs
    out[0]["content"] = "changed"
    assert msgs[0]["content"] == "ab"


def test_drops_oldest_until_user_tokens_fit(fake_enc):
    msgs = [
        {"role": "user", "content": "aaa"},
        {"role": "assistant", "content": "bbbb"},
        {"role": "user", "content": "cc"},
    ]
    out = mtb.clip_openai_messages_by_user_token_budget(msgs, 5)
    # user tokens: 3+2=5 if all kept; budget 5 -> keep all
    assert [m["content"] for m in out] == ["aaa", "bbbb", "cc"]

    out2 = mtb.clip_openai_messages_by_user_token_budget(msgs, 2)
    # need user sum <=2: drop first user+assistant, keep cc
    assert [m["content"] for m in out2] == ["cc"]


def test_truncates_only_user_when_entire_history_is_one_oversized_turn(fake_enc):
    msgs = [{"role": "user", "content": "a" * 10}]
    out = mtb.clip_openai_messages_by_user_token_budget(msgs, 4)
    assert len(out) == 1
    assert out[0]["role"] == "user"
    assert out[0]["content"] == "x" * 4
