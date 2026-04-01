"""
companion/infra/db/relationship.py — ``relationship_state`` per (user_id, bot_id) + mood axis logic.

Public API:
  get_or_create_relationship — upsert row, return full state dict (includes internal mood axes)
  update_relationship_state — trust/resonance deltas forwarded to apply_relationship_turn_deltas
  refresh_relationship_mood_for_elapsed_time — time-based axis drift + mood label inertia (GET path)
  apply_relationship_turn_deltas — full turn: stats deltas, triggers, mood axes, prev_turn_triggers

Internal:
  _hours_since, _minutes_since — elapsed time helpers
  _derive_mood_baselines — default energy/irritation/outwardness (no direction keyword rules)
  _axes_state_from_cur — build axis dict from relationship row + domain defaults
  _mood_label_and_changed — trigger mood_override / mood_nudge + inertia (refresh passes none → label unchanged)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.errors import ForeignKeyViolation

from .bots import get_bot
from .internal import _coerce_prev_turn_triggers_list, _exec_fetch_one_row, _prev_turn_triggers_jsonb


def _hours_since(last_dt: datetime | None, now_dt: datetime) -> float:
    if last_dt is None:
        return 0.0
    now_ref = now_dt if last_dt.tzinfo is None else now_dt.astimezone(last_dt.tzinfo)
    delta = now_ref - last_dt
    return max(0.0, delta.total_seconds() / 3600.0)


def _minutes_since(last_dt: datetime | None, now_dt: datetime) -> float:
    return _hours_since(last_dt, now_dt) * 60.0


def _derive_mood_baselines(direction: str | None) -> tuple[float, float, float]:
    from companion.domain import relationship_triggers as rt

    _ = direction
    e = rt.DEFAULT_BASELINE_ENERGY
    i = rt.DEFAULT_BASELINE_IRRITATION
    o = rt.DEFAULT_BASELINE_OUTWARDNESS
    return (
        max(0.0, min(100.0, e)),
        max(0.0, min(100.0, i)),
        max(0.0, min(100.0, o)),
    )


def _axes_state_from_cur(cur: dict, rt: Any) -> dict:
    return {
        "energy": float(cur.get("energy", rt.DEFAULT_BASELINE_ENERGY)),
        "irritation": float(cur.get("irritation", rt.DEFAULT_BASELINE_IRRITATION)),
        "outwardness": float(cur.get("outwardness", rt.DEFAULT_BASELINE_OUTWARDNESS)),
        "baseline_energy": float(cur.get("baseline_energy", rt.DEFAULT_BASELINE_ENERGY)),
        "baseline_irritation": float(cur.get("baseline_irritation", rt.DEFAULT_BASELINE_IRRITATION)),
        "baseline_outwardness": float(cur.get("baseline_outwardness", rt.DEFAULT_BASELINE_OUTWARDNESS)),
    }


def _mood_label_and_changed(
    rt: Any,
    *,
    prev_mood: str,
    cur: dict,
    state: dict,
    now_ts: datetime,
    mood_override: str | None = None,
    mood_nudge: int = 0,
    mood_force: bool = False,
) -> tuple[str, bool]:
    """
    Mood label changes only from trigger ``mood_override`` or ``mood_nudge`` (LLM-classified triggers),
    plus inertia rules—not from axis thresholds or user text heuristics.
    """
    nudge = int(mood_nudge)
    if mood_override is not None:
        candidate = mood_override
        candidate_strength = 100.0
    elif nudge != 0:
        candidate = rt.apply_mood_nudge(prev_mood, nudge)
        candidate_strength = 50.0
    else:
        return prev_mood, False

    if candidate == prev_mood:
        return prev_mood, False

    minutes_since_change = _minutes_since(cur.get("last_mood_changed_at"), now_ts)
    current_strength = 0.0
    should_change = rt.should_change_mood_label(
        current_label=prev_mood,
        candidate_label=candidate,
        minutes_since_last_change=minutes_since_change,
        current_strength=current_strength,
        candidate_strength=candidate_strength,
        ignore_min_duration=bool(mood_force),
    )
    mood = candidate if should_change else prev_mood
    return mood, bool(should_change)


def get_or_create_relationship(
    user_id: int,
    bot_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """
    Returns relationship state including internal-only fields.
    Fields: trust, resonance, affection, openness, mood, mood_recent_bias, prev_turn_triggers,
    energy, irritation, outwardness, baseline_*, last_mood_*.
    """
    user_id = int(user_id)
    bot_id = int(bot_id)
    sql = """
    INSERT INTO relationship_state (
      bot_id, user_id,
      energy, irritation, outwardness,
      baseline_energy, baseline_irritation, baseline_outwardness
    )
    VALUES (
      %(bot_id)s, %(user_id)s,
      %(be)s, %(bi)s, %(bo)s,
      %(be)s, %(bi)s, %(bo)s
    )
    ON CONFLICT (bot_id) DO UPDATE
      SET user_id = relationship_state.user_id
    RETURNING trust, resonance, affection, openness, mood, mood_recent_bias, prev_turn_triggers,
              energy, irritation, outwardness,
              baseline_energy, baseline_irritation, baseline_outwardness,
              last_mood_update_at, last_mood_changed_at;
    """
    try:
        bot = get_bot(bot_id, user_id=user_id, conn=conn)
        if bot is None:
            raise ValueError("bot not found")
        base_e, base_i, base_o = _derive_mood_baselines(bot.get("direction"))
        row = _exec_fetch_one_row(
            sql,
            {"bot_id": bot_id, "user_id": user_id, "be": base_e, "bi": base_i, "bo": base_o},
            conn=conn,
        )
        if row is None:
            raise RuntimeError("UPSERT failed: no row returned")
        return {
            "trust": row[0],
            "resonance": row[1],
            "affection": row[2],
            "openness": row[3],
            "mood": row[4],
            "mood_recent_bias": int(row[5] or 0),
            "prev_turn_triggers": _coerce_prev_turn_triggers_list(row[6]),
            "energy": float(row[7]),
            "irritation": float(row[8]),
            "outwardness": float(row[9]),
            "baseline_energy": float(row[10]),
            "baseline_irritation": float(row[11]),
            "baseline_outwardness": float(row[12]),
            "last_mood_update_at": row[13],
            "last_mood_changed_at": row[14],
        }
    except ForeignKeyViolation:
        raise ValueError(f"user_id={user_id} not found")


def update_relationship_state(
    user_id: int,
    bot_id: int,
    trust_delta: int,
    resonance_delta: int,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """
    Update trust/resonance using deltas; keep affection/openness in sync.
    Stored mood label is unchanged here unless a later trigger pass applies override/nudge. Returns updated state dict.
    """
    return apply_relationship_turn_deltas(
        user_id=user_id,
        bot_id=bot_id,
        trust_delta=trust_delta,
        resonance_delta=resonance_delta,
        affection_delta=trust_delta,
        openness_delta=resonance_delta,
        conn=conn,
    )


def refresh_relationship_mood_for_elapsed_time(
    user_id: int,
    bot_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """
    Advance mood axes toward baseline by real time since last_mood_update_at.
    The displayed ``mood`` label is not recomputed from axes (only trigger override/nudge changes it).

    Does not touch trust/resonance/affection/openness, mood_recent_bias, or prev_turn_triggers.
    Used on GET relationship so the UI is not stale until the next chat message.

    Returns: trust, resonance, affection, openness, mood (same shape as relationship API metrics).
    """
    from companion.domain import relationship_triggers as rt

    user_id = int(user_id)
    bot_id = int(bot_id)
    bot = get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")

    cur = get_or_create_relationship(user_id, bot_id, conn=conn)
    now_ts = datetime.now(timezone.utc)
    hours_elapsed = _hours_since(cur.get("last_mood_update_at"), now_ts)
    if hours_elapsed <= 0:
        return {
            "trust": int(cur["trust"]),
            "resonance": int(cur["resonance"]),
            "affection": int(cur["affection"]),
            "openness": int(cur["openness"]),
            "mood": str(cur["mood"]),
        }

    prev_mood = str(cur["mood"])
    state = _axes_state_from_cur(cur, rt)
    state = rt.apply_time_recovery(state, hours_elapsed)
    mood, should_change = _mood_label_and_changed(
        rt,
        prev_mood=prev_mood,
        cur=cur,
        state=state,
        now_ts=now_ts,
        mood_override=None,
        mood_nudge=0,
    )

    row2 = _exec_fetch_one_row(
        """
        UPDATE relationship_state
        SET
          energy = %(energy)s,
          irritation = %(irritation)s,
          outwardness = %(outwardness)s,
          mood = %(mood)s,
          last_mood_update_at = %(updated_ts)s,
          last_mood_changed_at = CASE
            WHEN %(changed)s THEN %(updated_ts)s
            ELSE last_mood_changed_at
          END
        WHERE bot_id = %(bot_id)s AND user_id = %(user_id)s
        RETURNING trust, resonance, affection, openness, mood;
        """,
        {
            "bot_id": bot_id,
            "user_id": user_id,
            "energy": state["energy"],
            "irritation": state["irritation"],
            "outwardness": state["outwardness"],
            "mood": mood,
            "updated_ts": now_ts,
            "changed": should_change,
        },
        conn=conn,
    )
    if row2 is None:
        raise RuntimeError("UPDATE relationship_state (mood time refresh) failed")
    return {
        "trust": int(row2[0]),
        "resonance": int(row2[1]),
        "affection": int(row2[2]),
        "openness": int(row2[3]),
        "mood": str(row2[4]),
    }


def apply_relationship_turn_deltas(
    user_id: int,
    bot_id: int,
    trust_delta: int,
    resonance_delta: int,
    affection_delta: int,
    openness_delta: int,
    *,
    mood_override: str | None = None,
    mood_nudge: int = 0,
    mood_force: bool = False,
    trigger_ids: list[str] | None = None,
    user_message: str = "",
    interest_match: bool = False,
    user_short_reply: bool = False,
    long_dialogue: bool = False,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """
    Apply independent deltas to trust/resonance/affection/openness (each clamped 0–100).
    Mood uses persistent axes (time recovery only) + trigger-driven label changes (override/nudge) + inertia.
    If trigger_ids is not None, replaces prev_turn_triggers for next turn's repeat decay.
    """
    from companion.domain import relationship_triggers as rt

    user_id = int(user_id)
    bot_id = int(bot_id)
    trust_delta = int(trust_delta)
    resonance_delta = int(resonance_delta)
    affection_delta = int(affection_delta)
    openness_delta = int(openness_delta)
    mood_nudge = int(mood_nudge)

    bot = get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")

    cur = get_or_create_relationship(user_id, bot_id, conn=conn)
    t = max(0, min(100, int(cur["trust"]) + trust_delta))
    r = max(0, min(100, int(cur["resonance"]) + resonance_delta))
    a = max(0, min(100, int(cur["affection"]) + affection_delta))
    o = max(0, min(100, int(cur["openness"]) + openness_delta))
    prev_mood = str(cur["mood"])
    old_bias = int(cur.get("mood_recent_bias") or 0)

    if mood_override is not None and mood_override not in rt.VALID_MOODS:
        mood_override = None

    now_ts = datetime.now(timezone.utc)
    state = _axes_state_from_cur(cur, rt)
    hours_elapsed = _hours_since(cur.get("last_mood_update_at"), now_ts)
    state = rt.apply_time_recovery(state, hours_elapsed)
    state = rt.apply_conversation_event_to_mood(
        state,
        trust_delta=trust_delta,
        resonance_delta=resonance_delta,
        mood_override=mood_override,
        mood_nudge=mood_nudge,
        trigger_ids=trigger_ids,
        user_message=user_message,
        interest_match=interest_match,
        user_short_reply=user_short_reply,
        long_dialogue=long_dialogue,
    )
    mood, should_change = _mood_label_and_changed(
        rt,
        prev_mood=prev_mood,
        cur=cur,
        state=state,
        now_ts=now_ts,
        mood_override=mood_override,
        mood_nudge=mood_nudge,
        mood_force=bool(mood_force),
    )

    had_override = mood_override is not None
    new_bias = rt.next_mood_bias_after_turn(old_bias, mood_nudge, had_override=had_override)
    if trigger_ids is None:
        new_prev = cur.get("prev_turn_triggers")
    else:
        new_prev = list(trigger_ids)

    row2 = _exec_fetch_one_row(
        """
        UPDATE relationship_state
        SET
          trust = %(t)s,
          resonance = %(r)s,
          affection = %(a)s,
          openness = %(o)s,
          mood = %(mood)s,
          energy = %(energy)s,
          irritation = %(irritation)s,
          outwardness = %(outwardness)s,
          last_mood_update_at = %(updated_ts)s,
          last_mood_changed_at = CASE
            WHEN %(changed)s THEN %(updated_ts)s
            ELSE last_mood_changed_at
          END,
          mood_recent_bias = %(mb)s,
          prev_turn_triggers = %(pt)s
        WHERE bot_id = %(bot_id)s AND user_id = %(user_id)s
        RETURNING trust, resonance, affection, openness, mood;
        """,
        {
            "bot_id": bot_id,
            "user_id": user_id,
            "t": t,
            "r": r,
            "a": a,
            "o": o,
            "mood": mood,
            "energy": state["energy"],
            "irritation": state["irritation"],
            "outwardness": state["outwardness"],
            "updated_ts": now_ts,
            "changed": should_change,
            "mb": new_bias,
            "pt": _prev_turn_triggers_jsonb(new_prev),
        },
        conn=conn,
    )
    if row2 is None:
        raise RuntimeError("UPDATE relationship_state failed")
    return {
        "trust": int(row2[0]),
        "resonance": int(row2[1]),
        "affection": int(row2[2]),
        "openness": int(row2[3]),
        "mood": str(row2[4]),
    }
