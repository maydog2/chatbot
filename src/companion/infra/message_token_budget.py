"""
message_token_budget.py — Trim chat ``messages`` so user-role contents stay within a token budget.

Used before the main chat completion so long transcripts (e.g. last 50 turns) do not blow the context.
Env: CHATBOT_USER_PROMPT_TOKEN_BUDGET — max tokens summed over all ``user`` contents in the list (0 = disable).
"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

_budget_encoder: Any = None


def _encoding_for_chat_model() -> Any:
    global _budget_encoder
    if _budget_encoder is not None:
        return _budget_encoder
    import tiktoken

    model = (os.getenv("OPENAI_MODEL") or "gpt-4o").strip()
    try:
        _budget_encoder = tiktoken.encoding_for_model(model)
    except KeyError:
        _budget_encoder = tiktoken.get_encoding("cl100k_base")
    return _budget_encoder


def user_prompt_token_budget() -> int:
    raw = (os.getenv("CHATBOT_USER_PROMPT_TOKEN_BUDGET") or "2000").strip()
    try:
        return int(raw)
    except ValueError:
        return 2000


def _user_token_sum(enc: Any, messages: list[dict[str, str]]) -> int:
    n = 0
    for m in messages:
        if (m.get("role") or "") != "user":
            continue
        n += len(enc.encode(str(m.get("content") or "")))
    return n


def _truncate_user_content(enc: Any, content: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    toks = enc.encode(content or "")
    if len(toks) <= max_tokens:
        return content or ""
    return enc.decode(toks[:max_tokens])


def clip_openai_messages_by_user_token_budget(
    messages: list[dict[str, str]],
    max_user_tokens: int,
) -> list[dict[str, str]]:
    """
    Return a shallow-copied message list, oldest-first, dropping a prefix of whole messages until
    the sum of tiktoken counts over all ``user`` ``content`` strings is <= ``max_user_tokens``.

    If ``max_user_tokens`` <= 0, returns a deep copy of ``messages`` (no clipping).
    If the last message alone is a user over budget, keeps only that turn with content truncated to the budget.
    """
    if not messages:
        return []
    if max_user_tokens <= 0:
        return deepcopy(messages)

    enc = _encoding_for_chat_model()
    p = 0
    while p < len(messages) and _user_token_sum(enc, messages[p:]) > max_user_tokens:
        p += 1
    out = [dict(m) for m in messages[p:]]
    if not out:
        last = messages[-1]
        role = str(last.get("role") or "")
        if role == "user":
            return [
                {
                    "role": "user",
                    "content": _truncate_user_content(
                        enc, str(last.get("content") or ""), max_user_tokens
                    ),
                }
            ]
        return [dict(last)]

    return out
