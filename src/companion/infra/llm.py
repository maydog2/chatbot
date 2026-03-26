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
  CHATBOT_TONE_MODEL — model for tone classifier (default gpt-4o-mini); CHATBOT_HOSTILITY_MODEL still accepted as alias
"""

from __future__ import annotations

import json
import os
import re


def _client():
    from openai import OpenAI

    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set. Set it to use AI chat.")
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
    return OpenAI(api_key=key, base_url=base_url)


def get_reply(messages: list[dict[str, str]]) -> str:
    """
    messages: list of {"role": "user"|"assistant"|"system", "content": "..."}
    Returns the assistant reply text.
    """
    client = _client()
    model = (os.getenv("OPENAI_MODEL") or "gpt-4o").strip()
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=1024,
    )
    choice = resp.choices and resp.choices[0]
    if not choice or not choice.message or not choice.message.content:
        return ""
    return choice.message.content.strip()


def _parse_tone_object(raw: str) -> tuple[bool | None, bool | None]:
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
        hostile = bool(obj["hostile"])
    if "warm" in obj:
        warm = bool(obj["warm"])
    if hostile is None and warm is None:
        return None, None
    return hostile, warm


def classify_user_tone_for_initiative(
    *,
    latest_user_message: str,
    transcript: str = "",
) -> tuple[bool | None, bool | None]:
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
    model = (
        os.getenv("CHATBOT_TONE_MODEL")
        or os.getenv("CHATBOT_HOSTILITY_MODEL")
        or "gpt-4o-mini"
    ).strip()
    sys_msg = (
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
    ctx = (transcript or "").strip()
    if ctx:
        user_block = (
            "Prior conversation (oldest first):\n"
            f"{ctx[:6000]}\n\n"
            "Latest user message (classify this one):\n"
            f"{latest[:2000]}"
        )
    else:
        user_block = f"Latest user message:\n{latest[:2000]}"
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sys_msg},
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
        return None, None
    h, w = _parse_tone_object(raw)
    if h is None and w is None:
        compact = re.sub(r"\s+", "", raw.lower())
        if '"hostile":true' in compact:
            h = True
        elif '"hostile":false' in compact:
            h = False
        if '"warm":true' in compact:
            w = True
        elif '"warm":false' in compact:
            w = False
    return h, w
