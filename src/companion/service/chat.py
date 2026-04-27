"""
Chat-turn orchestration for custom companion bots.
"""
from __future__ import annotations

import json
import logging
import os
import sys
from typing import Optional

import psycopg
from openai import AuthenticationError

from companion.domain import gomoku_relationship
from companion.domain import initiative as bot_initiative
from companion.domain import interests
from companion.infra import db, llm
from companion.infra.message_token_budget import (
    clip_openai_messages_by_user_token_budget,
    user_prompt_token_budget,
)

from . import reply_postprocess
from .bots import _interests_from_bot
from .gomoku import _gomoku_position_summary_for_prompt, _gomoku_side_chat_reply_rules
from .persona_guard import build_persona_rewrite_instruction, detect_persona_violations
from .relationships import apply_relationship_triggers_after_turn
from .system_prompt import build_system_prompt_from_direction
from .users import effective_form_of_address

logger = logging.getLogger(__name__)

_companion_stderr_logging_ready = False


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


def get_history_for_bot(
    user_id: int,
    bot_id: int,
    limit: int = 50,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    """Get message history for this bot (bot has one session)."""
    bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")
    return db.get_messages_by_session(bot["session_id"], limit, conn=conn)


def ensure_active_session(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> int:
    return db.get_or_create_session(user_id, conn=conn)


def end_current_session(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    sid = db.get_active_session_id(user_id, conn=conn)
    if sid is None:
        return False
    return db.end_session(sid, conn=conn)


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
    budget = user_prompt_token_budget()
    if budget > 0:
        messages = clip_openai_messages_by_user_token_budget(messages, budget)
    api_messages = [{"role": "system", "content": system_prompt_str}] + messages
    try:
        text = llm.get_reply(api_messages) or ""
        if not text.strip():
            logger.warning("get_reply_for_custom_bot: LLM returned empty content")
        return text
    except AuthenticationError:
        logger.exception("get_reply_for_custom_bot: LLM API key invalid or revoked (401)")
        raise RuntimeError(
            "The configured LLM API key was rejected (401 invalid_api_key). "
            "Check RESPAN_API_KEY or OPENAI_API_KEY, verify the matching base URL/model, then restart uvicorn."
        ) from None
    except Exception:
        logger.exception("get_reply_for_custom_bot: LLM call failed (see traceback below)")
        return "Sorry, I couldn't generate a response right now. Please try again."


def _maybe_rewrite_persona_break(
    *,
    openai_messages: list[dict[str, str]],
    turn_system: str,
    latest_user_message: str,
    draft_reply: str,
) -> str:
    violations = detect_persona_violations(draft_reply)
    if not violations:
        return draft_reply

    instruction = build_persona_rewrite_instruction(
        latest_user_message=latest_user_message,
        draft_reply=draft_reply,
        violations=violations,
    )
    rewrite_messages = openai_messages + [{"role": "user", "content": instruction}]
    rewritten = get_reply_for_custom_bot(rewrite_messages, turn_system)
    if not rewritten.strip():
        logger.warning("persona rewrite returned empty reply; keeping original draft")
        return draft_reply
    return rewritten


def send_bot_message(
    user_id: int,
    bot_id: int,
    content: str,
    system_prompt: str,
    *,
    trust_delta: int = 0,
    resonance_delta: int = 0,
    include_initiative_debug: bool = False,
    ephemeral_game: Optional[dict] = None,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """Bot has one session; save user message, get reply, save assistant message, return reply.

    If ``ephemeral_game`` is set, user/assistant for this turn are not written to ``messages``;
    the client sends prior in-game lines in ``game_messages``. Main session history still
    supplies long-term character context.
    """
    _ = system_prompt  # Client sends DB-cached copy; LLM uses rebuilt turn_system below.
    bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")
    if trust_delta or resonance_delta:
        db.update_relationship_state(
            user_id, bot_id, trust_delta, resonance_delta, conn=conn
        )
    sid = bot["session_id"]
    # Persist chat turns even during minigames, so the transcript remains continuous.
    mid_user = db.create_message(user_id, sid, "user", content, conn=conn)
    msgs = db.get_messages_by_session(sid, limit=50, conn=conn)
    openai_messages = [{"role": m["role"], "content": m["content"]} for m in msgs]
    if ephemeral_game:
        # The current minigame exchange is persisted above, so we do not append `game_messages`
        # or duplicate the current user content here. `position_summary` is still used later
        # for Gomoku constraints and tone alignment.
        pass
    direction = (bot.get("direction") or "").strip() or "a helpful, friendly companion"
    eff_addr = effective_form_of_address(bot.get("form_of_address"), user_id, conn=conn)
    p_int, s_int = _interests_from_bot(bot)

    # Optional: apply deterministic relationship deltas from minigame events
    # before building the prompt for this turn (so mood/stats can influence tone).
    gomoku_eff: gomoku_relationship.GomokuRelationshipEffect | None = None
    if ephemeral_game:
        pos = ephemeral_game.get("position_summary") if isinstance(ephemeral_game, dict) else None
        rel_events: list[str] = []
        raw_client_events = (ephemeral_game.get("relationship_events") or []) if isinstance(ephemeral_game, dict) else []
        if isinstance(raw_client_events, list):
            rel_events.extend([str(x) for x in raw_client_events if str(x).strip()])
        if isinstance(pos, dict):
            evs = pos.get("events")
            if isinstance(evs, list):
                if "user_created_threat" in evs:
                    rel_events.append("user_created_strong_threat")
                if "user_blocked_bot_threat" in evs:
                    rel_events.append("user_blocked_bot_threat")
            mr = pos.get("match_result")
            if mr in ("user_win", "bot_win"):
                rel_events.append(str(mr))
        seen: set[str] = set()
        rel_events = [e for e in rel_events if not (e in seen or seen.add(e))]
        gomoku_eff = gomoku_relationship.aggregate_gomoku_relationship_effects(rel_events)
        db.apply_relationship_turn_deltas(
            user_id=user_id,
            bot_id=bot_id,
            trust_delta=gomoku_eff.trust,
            resonance_delta=gomoku_eff.resonance,
            affection_delta=gomoku_eff.affection,
            openness_delta=gomoku_eff.openness,
            mood_override=gomoku_eff.mood_override,
            mood_nudge=gomoku_eff.mood_nudge,
            mood_force=True,
            user_message=content,
            conn=conn,
        )
    else:
        # Normal chat turn: write a "heartbeat" turn so mood time recovery / bias can progress.
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
    if ephemeral_game:
        ag = ephemeral_game.get("active_game") or {}
        diff = str(ag.get("difficulty", "serious"))
        turn_now = str(ag.get("current_turn", "user"))
        bside = str(ag.get("bot_side", "white"))
        turn_system += (
            "\n\n[Minigame side-chat — this user/assistant exchange is not saved to the main transcript. "
            "Stay in character; keep replies concise when they are chatting during play.]\n"
            "You are playing Gomoku (five in a row) with the user on a 12×12 board (standard consecutive-five win). "
            f"Difficulty setting: {diff}. "
            f"The user plays black stones; you (the character) play {bside} stones. "
            f"Whose turn it is to place a stone on the board right now: {turn_now} "
            "(if ‘user’, they should move on the board but may still type here; if ‘bot’, you should move on the board when it is your turn). "
            "If the board analysis says the match has ended, treat that as authoritative and ignore this turn line. "
            "If they mention the game or the board, respond as their in-character opponent—not a coach (follow the "
            "Gomoku side-chat rules appended below)."
        )
        pos_raw = ephemeral_game.get("position_summary")
        pos_txt = _gomoku_position_summary_for_prompt(pos_raw)
        if os.getenv("CHATBOT_LOG_GOMOKU_SUMMARY", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            ensure_companion_stderr_logging()
            logger.info(
                "[gomoku ephemeral] user_id=%s bot_id=%s position_summary=%s",
                user_id,
                bot_id,
                "yes" if pos_raw is not None else "no",
            )
            if pos_raw is not None:
                try:
                    dbg_json = json.dumps(pos_raw, ensure_ascii=False, indent=2)
                except (TypeError, ValueError):
                    dbg_json = repr(pos_raw)
                logger.info("gomoku position_summary JSON:\n%s", dbg_json)
                if pos_txt:
                    logger.info("gomoku position_summary prompt block:\n%s", pos_txt)
        if pos_txt:
            turn_system += (
                "\n\n[Board analysis — computed on the client from the live grid; trust this over guessing. "
                "Coordinates are 0-based: x = column, y = row.]\n"
                f"{pos_txt}"
            )
        turn_system += "\n\n" + _gomoku_side_chat_reply_rules(pos_raw if isinstance(pos_raw, dict) else {})
    reply = get_reply_for_custom_bot(openai_messages, turn_system)
    reply = _maybe_rewrite_persona_break(
        openai_messages=openai_messages,
        turn_system=turn_system,
        latest_user_message=content,
        draft_reply=reply,
    )
    reply = reply_postprocess.enforce_initiative_closing_question(reply, str(ini_snap["band"]))
    mid_assistant = db.create_message(user_id, sid, "assistant", reply, conn=conn)
    apply_relationship_triggers_after_turn(user_id, bot_id, content, reply, conn=conn)
    # Ensure Gomoku mood hint survives any trigger-based mood change in the same turn.
    # Apply again with zero stat deltas (no double counting), subject to mood inertia.
    if gomoku_eff and (gomoku_eff.mood_override or gomoku_eff.mood_nudge):
        db.apply_relationship_turn_deltas(
            user_id=user_id,
            bot_id=bot_id,
            trust_delta=0,
            resonance_delta=0,
            affection_delta=0,
            openness_delta=0,
            mood_override=gomoku_eff.mood_override,
            mood_nudge=gomoku_eff.mood_nudge,
            mood_force=True,
            user_message=content,
            conn=conn,
        )
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
