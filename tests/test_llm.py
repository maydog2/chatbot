from __future__ import annotations

from typing import Any

import pytest

from companion.infra import llm


def test_parse_tone_object_handles_string_false_values() -> None:
    assert llm._parse_tone_object('{"hostile": "false", "warm": "true"}') == (False, True)


def test_memory_extractor_prompt_limits_extraction_to_latest_user_message() -> None:
    prompt = llm._MEMORY_EXTRACTOR_SYSTEM_PROMPT

    assert "latest user message" in prompt
    assert "Use recent context only to disambiguate corrections or replacements" in prompt
    assert "do not extract or repeat memories that appear only in recent context" in prompt


def test_client_reuses_cached_openai_client_for_same_env(monkeypatch: pytest.MonkeyPatch) -> None:
    created: list[Any] = []

    class FakeOpenAI:
        def __init__(
            self,
            *,
            api_key: str,
            base_url: str | None = None,
            timeout: float | None = None,
        ) -> None:
            self.api_key = api_key
            self.base_url = base_url
            self.timeout = timeout
            created.append(self)

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(llm, "_CACHED_CLIENT", None)
    monkeypatch.setattr(llm, "_CACHED_CLIENT_CONFIG", None)
    monkeypatch.setenv("OPENAI_API_KEY", "key-1")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_TIMEOUT_SECONDS", raising=False)

    first = llm._client()
    second = llm._client()

    assert first is second
    assert len(created) == 1

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    third = llm._client()

    assert third is not first
    assert len(created) == 2
