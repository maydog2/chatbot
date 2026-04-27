"""
Relationship state service operations and post-turn trigger application.
"""
from __future__ import annotations

import logging
from typing import Optional

import psycopg

from companion.domain import interests, relationship_triggers
from companion.infra import db

from .bots import _interests_from_bot

logger = logging.getLogger(__name__)


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


def get_relationship(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> tuple[int, int]:
    """Trust/resonance for the user's first bot, or schema defaults if they have no bots yet."""
    bots = db.get_bots_by_user(user_id, conn=conn)
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
