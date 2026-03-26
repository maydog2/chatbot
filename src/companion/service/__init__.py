"""
companion/service/__init__.py — application orchestration (chat, bots, relationship, profile).

Import path: ``import companion.service as service`` (used by api, CLI, tests).

Public API (re-exported on ``companion.service``):
  Auth / users: register_user, login, logout, issue_access_token, get_user_id_from_token
  Profile: get_me, update_me, get_display_name
  Chat: get_history_for_bot, send_and_get_history, send_bot_message, get_reply_for_custom_bot
  Relationship: apply_relationship_triggers_after_turn, get_relationship, get_relationship_public
  Bots: create_bot, update_bot, get_bots_by_user, delete_bot
  Sessions (legacy user session): ensure_active_session, end_current_session
  Prompt / addressing: build_system_prompt_from_direction, effective_form_of_address,
    interests_tuple_for_prompt
  Logging: ensure_companion_stderr_logging

Also re-exported from submodules for stable names on ``service``:
  register_user, login (users); issue_access_token, get_user_id_from_token, logout (auth_tokens);
  build_system_prompt_from_direction (system_prompt).

Internal / test hooks (leading underscore; not for callers outside tests/maintenance):
  _interests_from_bot — interest tuple from bot row dict
  _strip_roleplay_sensory_disclaimers, _enforce_initiative_closing_question — aliases of
    reply_postprocess helpers for tests that monkeypatch ``companion.service.*``

Implementation modules: users.py, auth_tokens.py, system_prompt.py, reply_postprocess.py.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import psycopg
from openai import AuthenticationError

from companion.domain import initiative as bot_initiative, interests, relationship_triggers
from companion.infra import db, llm

from . import auth_tokens, reply_postprocess, system_prompt, users

logger = logging.getLogger(__name__)

_companion_stderr_logging_ready = False

# Re-export auth & users (stable import path: companion.service)
register_user = users.register_user
login = users.login
issue_access_token = auth_tokens.issue_access_token
get_user_id_from_token = auth_tokens.get_user_id_from_token
logout = auth_tokens.logout
build_system_prompt_from_direction = system_prompt.build_system_prompt_from_direction

# Re-export for tests that patch companion.service._strip_*
_strip_roleplay_sensory_disclaimers = reply_postprocess.strip_roleplay_sensory_disclaimers
_enforce_initiative_closing_question = reply_postprocess.enforce_initiative_closing_question


def _initiative_tone_llm_enabled() -> bool:
    if os.getenv("CHATBOT_INITIATIVE_TONE_LLM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return True
    return os.getenv("CHATBOT_INITIATIVE_HOSTILITY_LLM", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _transcript_snippet_for_tone_llm(messages: list[dict[str, str]], max_messages: int = 10) -> str:
    """Oldest-first tail for initiative tone classifier (disambiguate shifts)."""
    tail = messages[-max_messages:] if len(messages) > max_messages else messages
    lines: list[str] = []
    for m in tail:
        role = str(m.get("role") or "")
        content = (str(m.get("content") or "")).strip()
        if not content:
            continue
        if role == "user":
            label = "User"
        elif role == "assistant":
            label = "Assistant"
        else:
            label = role.capitalize() or "?"
        lines.append(f"{label}: {content[:800]}")
    return "\n".join(lines)


def ensure_companion_stderr_logging() -> None:
    """
    Uvicorn configures uvicorn.* loggers but not the root logger; companion.* INFO would otherwise be dropped.
    Safe to call multiple times (e.g. from API lifespan and from send_bot_message).
    """
    global _companion_stderr_logging_ready
    if _companion_stderr_logging_ready:
        return
    _companion_stderr_logging_ready = True
    clog = logging.getLogger("companion")
    clog.setLevel(logging.INFO)
    if not clog.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        clog.addHandler(h)
    clog.propagate = False


def _interests_from_bot(bot: dict) -> tuple[str | None, list[str]]:
    p = bot.get("primary_interest")
    p = None if p is None or not str(p).strip() else str(p).strip()
    s = bot.get("secondary_interests")
    if not isinstance(s, list):
        s = []
    return p, [str(x) for x in s]


def interests_tuple_for_prompt(bot: dict) -> tuple[str | None, list[str]]:
    """Public helper for API preview routes."""
    return _interests_from_bot(bot)


def effective_form_of_address(
    explicit: str | None,
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> str:
    """
    Text the model should use to address the user: per-bot form_of_address if set,
    otherwise the user's profile display_name (nickname). Empty explicit falls through to display_name.
    """
    s = (explicit or "").strip()
    if s:
        return s
    return (db.get_display_name(user_id, conn=conn) or "").strip()


def get_history_for_bot(
    user_id: int,
    bot_id: int,
    limit: int = 50,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    """Get message history for this bot (bot has one session). Returns [] if bot not found."""
    bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        return []
    return db.get_messages_by_session(bot["session_id"], limit, conn=conn)


def send_and_get_history(
    user_id: int,
    bot_id: int,
    content: str,
    limit: int = 50,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")
    sp = str(bot.get("system_prompt") or "")
    result = send_bot_message(user_id, bot_id, content, sp, conn=conn)
    result["history"] = get_history_for_bot(user_id, bot_id, limit, conn=conn)
    return result


def ensure_active_session(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    return db.get_or_create_session(user_id, conn=conn)


def apply_relationship_triggers_after_turn(
    user_id: int,
    bot_id: int,
    user_message: str,
    assistant_message: str,
    conn: Optional[psycopg.Connection] = None,
) -> None:
    """
    Classify the turn into trigger IDs (no raw scores from the model), then apply fixed deltas in db.
    Safe no-op if classification fails or returns nothing.
    """
    try:
        cur = db.get_or_create_relationship(user_id, bot_id, conn=conn)
        bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
        p_int, s_int = _interests_from_bot(bot or {})
        msg = (user_message or "").strip()
        short_reply = len(msg) <= 12 or len(msg.split()) <= 3
        sid = int((bot or {}).get("session_id") or 0)
        long_dialogue = False
        if sid > 0:
            hist = db.get_messages_by_session(sid, limit=20, conn=conn)
            long_dialogue = len(hist) >= 14
        labels = [interests.INTEREST_LABELS.get(p_int, p_int)] + [
            interests.INTEREST_LABELS.get(k, k) for k in s_int
        ]
        lower_msg = msg.lower()
        interest_match = any(lab and lab.lower() in lower_msg for lab in labels if lab)
        prev = frozenset(cur.get("prev_turn_triggers") or [])
        tids = relationship_triggers.classify_triggers_llm(user_message, assistant_message)
        dt, dr, da, do, mood_override, mood_nudge = relationship_triggers.aggregate_trigger_effects(
            tids,
            previous_turn_trigger_ids=prev,
        )
        dt, dr, da, do = relationship_triggers.dampen_positive_stats_deltas_for_mood(
            dt, dr, da, do, mood=str(cur.get("mood") or "Calm")
        )
        if (
            dt == dr == da == do == 0
            and mood_override is None
            and mood_nudge == 0
            and not short_reply
            and not long_dialogue
            and not interest_match
        ):
            return
        db.apply_relationship_turn_deltas(
            user_id,
            bot_id,
            dt,
            dr,
            da,
            do,
            mood_override=mood_override,
            mood_nudge=mood_nudge,
            trigger_ids=tids,
            user_message=user_message,
            interest_match=interest_match,
            user_short_reply=short_reply,
            long_dialogue=long_dialogue,
            conn=conn,
        )
    except Exception:
        logger.exception(
            "apply_relationship_triggers_after_turn failed user_id=%s bot_id=%s",
            user_id,
            bot_id,
        )


def get_reply_for_custom_bot(
    messages: list[dict[str, str]],
    system_prompt_str: str,
) -> str:
    """
    Get an assistant reply using a custom system prompt and conversation history.
    Does not save to DB. Used by send_bot_message after loading history from DB.
    messages: list of {"role": "user"|"assistant", "content": "..."}
    """
    if not messages:
        return ""
    api_messages = [{"role": "system", "content": system_prompt_str}] + messages
    try:
        text = llm.get_reply(api_messages) or ""
        if not text.strip():
            logger.warning("get_reply_for_custom_bot: LLM returned empty content")
        return text
    except AuthenticationError:
        logger.exception("get_reply_for_custom_bot: OpenAI API key invalid or revoked (401)")
        raise RuntimeError(
            "OPENAI_API_KEY was rejected by OpenAI (401 invalid_api_key). "
            "Create a new secret key at https://platform.openai.com/api-keys , paste the full sk-... string "
            "(no spaces or quotes), clear OPENAI_BASE_URL when using api.openai.com, then restart uvicorn."
        ) from None
    except Exception:
        logger.exception("get_reply_for_custom_bot: LLM call failed (see traceback below)")
        return "Sorry, I couldn't generate a response right now. Please try again."


def send_bot_message(
    user_id: int,
    bot_id: int,
    content: str,
    system_prompt: str,
    *,
    trust_delta: int = 0,
    resonance_delta: int = 0,
    include_initiative_debug: bool = False,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """Bot has one session; save user message, get reply, save assistant message, return reply."""
    _ = system_prompt  # Client sends DB-cached copy; LLM uses rebuilt turn_system below.
    bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")
    if trust_delta or resonance_delta:
        db.update_relationship_state(
            user_id, bot_id, trust_delta, resonance_delta, conn=conn
        )
    sid = bot["session_id"]
    mid_user = db.create_message(user_id, sid, "user", content, conn=conn)
    msgs = db.get_messages_by_session(sid, limit=50, conn=conn)
    openai_messages = [{"role": m["role"], "content": m["content"]} for m in msgs]
    direction = (bot.get("direction") or "").strip() or "a helpful, friendly companion"
    eff_addr = effective_form_of_address(bot.get("form_of_address"), user_id, conn=conn)
    p_int, s_int = _interests_from_bot(bot)
    db.apply_relationship_turn_deltas(
        user_id=user_id,
        bot_id=bot_id,
        trust_delta=0,
        resonance_delta=0,
        affection_delta=0,
        openness_delta=0,
        user_message=content,
        conn=conn,
    )
    rel = db.get_or_create_relationship(user_id, bot_id, conn=conn)
    dyn_prompt = build_system_prompt_from_direction(
        direction,
        trust=rel["trust"],
        resonance=rel["resonance"],
        affection=rel["affection"],
        openness=rel["openness"],
        mood=rel["mood"],
        form_of_address=eff_addr,
        character_name=str(bot.get("name") or "").strip(),
        primary_interest=p_int,
        secondary_interests=s_int,
    )
    nudge = interests.format_interests_dynamic_nudge(content, p_int, s_int)
    turn_system = dyn_prompt
    if nudge:
        turn_system += f"\n{nudge}"
    oa_for_ini: list[dict[str, str]] = [
        {"role": str(m["role"]), "content": str(m.get("content") or "")} for m in openai_messages
    ]
    hostile_hint: bool | None = None
    warm_hint: bool | None = None
    if _initiative_tone_llm_enabled():
        hostile_hint, warm_hint = llm.classify_user_tone_for_initiative(
            latest_user_message=content,
            transcript=_transcript_snippet_for_tone_llm(oa_for_ini),
        )
    ini_snap = bot_initiative.effective_initiative_snapshot(
        base_raw=bot.get("initiative"),
        trust=int(rel["trust"]),
        resonance=int(rel["resonance"]),
        primary_interest=p_int,
        secondary_interests=s_int,
        openai_messages=oa_for_ini,
        latest_user_content=content,
        hostile_hint=hostile_hint,
        warm_hint=warm_hint,
    )
    if os.getenv("CHATBOT_LOG_INITIATIVE", "").strip().lower() in ("1", "true", "yes", "on"):
        ensure_companion_stderr_logging()
        logger.info(
            "initiative bot_id=%s score=%.3f band=%s base=%s interest_match=%s mood=%s hostile=%s warm=%s",
            bot_id,
            ini_snap["score"],
            ini_snap["band"],
            ini_snap["base"],
            ini_snap["interest_match"],
            rel["mood"],
            ini_snap.get("hostile_source", "-"),
            ini_snap.get("warm_source", "-"),
        )
    turn_system += "\n" + bot_initiative.format_initiative_instruction(ini_snap["score"])
    vocative = (eff_addr or "").strip().replace('"', "'")
    if vocative:
        turn_system += (
            f'\n\nVocative (highest priority this turn): Address the user as "{vocative}" in this reply—'
            "greetings, sign-offs, and direct answers about what you call them. "
            "The transcript may still contain an old honorific; ignore it and do not claim the old one is your current habit."
        )
    reply = get_reply_for_custom_bot(openai_messages, turn_system)
    reply = reply_postprocess.strip_roleplay_sensory_disclaimers(reply)
    reply = reply_postprocess.enforce_initiative_closing_question(reply, str(ini_snap["band"]))
    mid_assistant = db.create_message(user_id, sid, "assistant", reply, conn=conn)
    apply_relationship_triggers_after_turn(user_id, bot_id, content, reply, conn=conn)
    rel_after = db.get_or_create_relationship(user_id, bot_id, conn=conn)
    out: dict = {
        "session_id": sid,
        "message_id": mid_user,
        "assistant_message_id": mid_assistant,
        "assistant_reply": reply,
        "trust": rel_after["trust"],
        "resonance": rel_after["resonance"],
        "affection": rel_after["affection"],
        "openness": rel_after["openness"],
        "mood": rel_after["mood"],
    }
    if include_initiative_debug:
        out["initiative_debug"] = ini_snap
    return out


def create_bot(
    user_id: int,
    name: str,
    direction: str,
    *,
    primary_interest: str,
    secondary_interests: Optional[list[str]] = None,
    avatar_data_url: Optional[str] = None,
    form_of_address: Optional[str] = None,
    initiative: str = "medium",
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """Build system prompt, create a new session, create bot bound to that session. Returns bot dict."""
    resolved_name = (name or "My Bot").strip()
    if db.user_has_duplicate_bot_name(user_id, resolved_name, conn=conn):
        raise ValueError("a bot with this name already exists")
    av = (avatar_data_url or "").strip() or None
    if av and db.user_has_duplicate_bot_avatar(user_id, av, conn=conn):
        raise ValueError("a bot with this avatar already exists")

    foa = (form_of_address or "").strip()
    eff_addr = effective_form_of_address(form_of_address, user_id, conn=conn)
    p_n, s_n = interests.normalize_bot_interests(primary_interest, secondary_interests or [])
    ini = bot_initiative.normalize_initiative(initiative)
    sp = build_system_prompt_from_direction(
        direction or "a helpful, friendly companion",
        trust=40,
        resonance=30,
        affection=40,
        openness=30,
        mood="Calm",
        form_of_address=eff_addr,
        character_name=resolved_name,
        primary_interest=p_n,
        secondary_interests=s_n,
    )
    session_id = db.create_session(user_id, conn=conn)
    bot_id = db.create_bot(
        user_id,
        session_id,
        name=resolved_name,
        system_prompt=sp,
        avatar_data_url=av,
        direction=direction or None,
        form_of_address=foa or None,
        primary_interest=p_n,
        secondary_interests=s_n,
        initiative=ini,
        conn=conn,
    )
    bot = db.get_bot(bot_id, conn=conn)
    assert bot is not None
    db.get_or_create_relationship(user_id, bot_id, conn=conn)
    return bot


def delete_bot(
    user_id: int,
    bot_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    """Delete bot and its session (messages CASCADE). Returns True if deleted."""
    return db.delete_bot(bot_id, user_id, conn=conn)


def get_bots_by_user(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    """List all bots for the user (from DB)."""
    return db.get_bots_by_user(user_id, conn=conn)


def update_bot(
    user_id: int,
    bot_id: int,
    *,
    name: str | None = None,
    direction: str | None = None,
    avatar_data_url: str | None = None,
    form_of_address: str | None = None,
    primary_interest: str | None = None,
    secondary_interests: list[str] | None = None,
    initiative: str | None = None,
    update_name: bool = False,
    update_direction: bool = False,
    update_avatar: bool = False,
    update_form_of_address: bool = False,
    update_primary_interest: bool = False,
    update_secondary_interests: bool = False,
    update_initiative: bool = False,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """
    Update bot fields and persist to DB.
    - If direction, form_of_address, or interests change, system_prompt is rebuilt using current relationship attributes.
    """
    bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")

    kwargs: dict[str, object] = {}
    if update_name:
        new_name_s = str(name or "").strip()
        if not new_name_s:
            raise ValueError("name must be non-empty")
        if db.user_has_duplicate_bot_name(user_id, new_name_s, exclude_bot_id=bot_id, conn=conn):
            raise ValueError("a bot with this name already exists")
        kwargs["name"] = name
    if update_avatar:
        if (
            avatar_data_url is not None
            and str(avatar_data_url).strip()
            and db.user_has_duplicate_bot_avatar(
                user_id, str(avatar_data_url).strip(), exclude_bot_id=bot_id, conn=conn
            )
        ):
            raise ValueError("a bot with this avatar already exists")
        kwargs["avatar_data_url"] = avatar_data_url

    update_interests = update_primary_interest or update_secondary_interests
    if update_interests:
        p_raw = primary_interest if update_primary_interest else bot.get("primary_interest")
        s_raw = (secondary_interests if update_secondary_interests else bot.get("secondary_interests")) or []
        if not isinstance(s_raw, list):
            s_raw = []
        p_stripped = (None if p_raw is None else str(p_raw).strip()) or None
        if not p_stripped:
            p_stripped = "self_growth"
        p_n, s_n = interests.normalize_bot_interests(p_stripped, list(s_raw))
        kwargs["primary_interest"] = p_n
        kwargs["secondary_interests"] = s_n

    if update_initiative:
        kwargs["initiative"] = bot_initiative.normalize_initiative(initiative)

    if update_direction or update_form_of_address or update_interests:
        rel = db.get_or_create_relationship(user_id, bot_id, conn=conn)
        if update_direction:
            new_dir = (direction or "").strip()
            kwargs["direction"] = new_dir or None
            dir_for_build = new_dir or "a helpful, friendly companion"
        else:
            dir_for_build = ((bot.get("direction") or "").strip() or "a helpful, friendly companion")
        if update_form_of_address:
            foa_stripped = ("" if form_of_address is None else str(form_of_address)).strip()
            kwargs["form_of_address"] = foa_stripped or None
            explicit_for_eff = foa_stripped
        else:
            explicit_for_eff = (bot.get("form_of_address") or "").strip()
        eff_addr = effective_form_of_address(explicit_for_eff or None, user_id, conn=conn)
        if update_interests:
            p_prompt = kwargs["primary_interest"]  # type: ignore[assignment]
            s_prompt = kwargs["secondary_interests"]  # type: ignore[assignment]
        else:
            p_prompt, s_prompt = _interests_from_bot(bot)
        char_label = str((name if update_name else bot.get("name")) or "").strip()
        sp = build_system_prompt_from_direction(
            dir_for_build,
            trust=rel["trust"],
            resonance=rel["resonance"],
            affection=rel["affection"],
            openness=rel["openness"],
            mood=rel["mood"],
            form_of_address=eff_addr,
            character_name=char_label,
            primary_interest=p_prompt,  # type: ignore[arg-type]
            secondary_interests=s_prompt,  # type: ignore[arg-type]
        )
        kwargs["system_prompt"] = sp

    updated = db.update_bot(bot_id, user_id, conn=conn, **kwargs)
    if updated is None:
        raise ValueError("bot not found")
    return updated


def end_current_session(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    sid = db.get_active_session_id(user_id, conn=conn)
    if sid is None:
        return False
    return db.end_session(sid, conn=conn)


def get_relationship(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> tuple[int, int]:
    """Trust/resonance for the user's first bot, or schema defaults if they have no bots yet."""
    bots = get_bots_by_user(user_id, conn=conn)
    if not bots:
        return 40, 30
    m = db.refresh_relationship_mood_for_elapsed_time(user_id, int(bots[0]["id"]), conn=conn)
    return m["trust"], m["resonance"]


def get_relationship_public(
    user_id: int,
    bot_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """Relationship state for UI (trust, resonance, affection, openness, mood)."""
    return db.refresh_relationship_mood_for_elapsed_time(user_id, bot_id, conn=conn)


def get_display_name(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> str | None:
    return db.get_display_name(user_id, conn=conn)


def get_me(user_id: int, conn: Optional[psycopg.Connection] = None) -> dict:
    display_name = db.get_display_name(user_id, conn=conn) or ""
    avatar = db.get_user_avatar_data_url(user_id, conn=conn)
    return {"display_name": display_name, "avatar_data_url": avatar}


def update_me(
    user_id: int,
    *,
    display_name: str | None = None,
    avatar_data_url: str | None = None,
    update_display_name: bool = False,
    update_avatar: bool = False,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    if update_display_name:
        assert display_name is not None
        db.update_user_display_name(user_id, display_name, conn=conn)
    if update_avatar:
        db.update_user_avatar_data_url(user_id, avatar_data_url, conn=conn)
    return get_me(user_id, conn=conn)
