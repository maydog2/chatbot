"""
companion/infra/llm.py — OpenAI-compatible chat completions.

Public API:
  get_reply(messages) — run chat completion; returns assistant text (raises if key missing)
  classify_user_tone_for_initiative(...) — one JSON call: (hostile, warm) hints for initiative nudges only

Internal:
  _client() — lazy OpenAI client from env (OPENAI_API_KEY, optional OPENAI_BASE_URL, OPENAI_MODEL)

Env:
  OPENAI_API_KEY — required for chat
  OPENAI_BASE_URL — optional (e.g. OpenRouter, Groq)
  OPENAI_MODEL — optional override (default gpt-4o in code)
  OPENAI_MAX_TOKENS — optional main reply token cap (default 1024)
  OPENAI_TIMEOUT_SECONDS — optional OpenAI client timeout
  CHATBOT_TONE_MODEL — model for tone classifier (default gpt-4o-mini); CHATBOT_HOSTILITY_MODEL still accepted as alias
"""

from __future__ import annotations

import json
import logging
import os
import re
from threading import Lock
from typing import Any, TypeAlias

logger = logging.getLogger(__name__)

ChatMessage: TypeAlias = dict[str, str]
ToneHint: TypeAlias = tuple[bool | None, bool | None]
_ClientConfig: TypeAlias = tuple[str, str | None, float | None]

_TONE_TRANSCRIPT_CHAR_LIMIT = 6000
_TONE_LATEST_CHAR_LIMIT = 2000
_TONE_CLASSIFIER_SYSTEM_PROMPT = (
    "You judge the USER's latest message in a chat with a fictional character bot. "
    "Reply with ONLY a JSON object, no other text:\n"
    '{"hostile": <true|false>, "warm": <true|false>}\n'
    "- hostile: insults, slurs, threats, dehumanizing language, or clear verbal abuse toward the bot. "
    "Mild frustration or disagreement without abuse is NOT hostile.\n"
    "- warm: clear positive social signal THIS turn toward the bot: thanks, genuine apology, de-escalation, "
    "explicit appreciation, or obvious softening/repair after tension. Routine neutral chat is NOT warm.\n"
    "If the latest message is neither hostile nor specially warm, set both to false.\n"
    "Use prior lines only to disambiguate (e.g. tone shift, sarcasm, or repair)."
)

_CACHED_CLIENT: Any | None = None
_CACHED_CLIENT_CONFIG: _ClientConfig | None = None
_CLIENT_LOCK = Lock()


def _positive_int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _positive_float_env(name: str) -> float | None:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _main_model() -> str:
    return (os.getenv("OPENAI_MODEL") or "gpt-4o").strip()


def _main_max_tokens() -> int:
    return _positive_int_env("OPENAI_MAX_TOKENS", 1024)


def _tone_model() -> str:
    return (
        os.getenv("CHATBOT_TONE_MODEL")
        or os.getenv("CHATBOT_HOSTILITY_MODEL")
        or "gpt-4o-mini"
    ).strip()


def _client() -> Any:
    global _CACHED_CLIENT, _CACHED_CLIENT_CONFIG

    from openai import OpenAI

    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set. Set it to use AI chat.")
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
    timeout = _positive_float_env("OPENAI_TIMEOUT_SECONDS")
    config = (key, base_url, timeout)
    if _CACHED_CLIENT is not None and _CACHED_CLIENT_CONFIG == config:
        return _CACHED_CLIENT
    with _CLIENT_LOCK:
        if _CACHED_CLIENT is not None and _CACHED_CLIENT_CONFIG == config:
            return _CACHED_CLIENT
        _CACHED_CLIENT = OpenAI(api_key=key, base_url=base_url, timeout=timeout)
        _CACHED_CLIENT_CONFIG = config
        return _CACHED_CLIENT


def get_reply(messages: list[ChatMessage]) -> str:
    """
    messages: list of {"role": "user"|"assistant"|"system", "content": "..."}
    Returns the assistant reply text.
    """
    client = _client()
    resp = client.chat.completions.create(
        model=_main_model(),
        messages=messages,
        max_tokens=_main_max_tokens(),
    )
    choice = resp.choices and resp.choices[0]
    if not choice or not choice.message or not choice.message.content:
        return ""
    return choice.message.content.strip()


def _coerce_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "true":
            return True
        if normalized == "false":
            return False
    return None


def _parse_tone_object(raw: str) -> ToneHint:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None, None
    if not isinstance(obj, dict):
        return None, None
    hostile: bool | None = None
    warm: bool | None = None
    if "hostile" in obj:
        hostile = _coerce_bool(obj["hostile"])
    if "warm" in obj:
        warm = _coerce_bool(obj["warm"])
    if hostile is None and warm is None:
        return None, None
    return hostile, warm


def _parse_tone_object_fallback(raw: str) -> ToneHint:
    compact = re.sub(r"\s+", "", raw.lower())
    hostile: bool | None = None
    warm: bool | None = None
    if '"hostile":true' in compact:
        hostile = True
    elif '"hostile":false' in compact:
        hostile = False
    if '"warm":true' in compact:
        warm = True
    elif '"warm":false' in compact:
        warm = False
    return hostile, warm


def classify_user_tone_for_initiative(
    *,
    latest_user_message: str,
    transcript: str = "",
) -> ToneHint:
    """
    Initiative-only (not moderation). Returns (hostile_hint, warm_hint); each None if missing from parse
    or whole call skipped/failed. Prior transcript helps disambiguate tone shifts (e.g. apology after conflict).
    """
    latest = (latest_user_message or "").strip()
    if not latest:
        return None, None
    try:
        client = _client()
    except RuntimeError:
        return None, None
    ctx = (transcript or "").strip()
    if ctx:
        user_block = (
            "Prior conversation (oldest first):\n"
            f"{ctx[:_TONE_TRANSCRIPT_CHAR_LIMIT]}\n\n"
            "Latest user message (classify this one):\n"
            f"{latest[:_TONE_LATEST_CHAR_LIMIT]}"
        )
    else:
        user_block = f"Latest user message:\n{latest[:_TONE_LATEST_CHAR_LIMIT]}"
    try:
        resp = client.chat.completions.create(
            model=_tone_model(),
            messages=[
                {"role": "system", "content": _TONE_CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": user_block},
            ],
            max_tokens=64,
            temperature=0,
        )
        ch0 = resp.choices[0] if resp.choices else None
        if not ch0 or not ch0.message:
            return None, None
        raw = (ch0.message.content or "").strip()
    except Exception:
        logger.debug("classify_user_tone_for_initiative: LLM tone call failed", exc_info=True)
        return None, None
    h, w = _parse_tone_object(raw)
    if h is None and w is None:
        h, w = _parse_tone_object_fallback(raw)
    return h, w
