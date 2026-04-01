"""
companion/domain/relationship_triggers.py — Turn-level relationship/mood rules (triggers + axis model).

The classifier returns trigger IDs only; numeric trust/resonance/affection/openness deltas and
trigger mood_override / mood_nudge are applied in ``db`` (label path). Mood axes only drift via
time recovery—conversation no longer applies hardcoded axis formulas. Used by ``db.apply_relationship_turn_deltas``
and related read paths.

Public API (selection):
  trigger_ids_for_prompt — IDs exposed to the classification prompt
  aggregate_trigger_effects — merge trigger list → t/r/a/o deltas + mood_override + mood_nudge
  dampen_positive_stats_deltas_for_mood — scale down positive t/r/a/o while Irritated (service applies after aggregate)
  classify_triggers_llm — LLM call: user+assistant text → trigger id list (empty on failure)
  apply_time_recovery — decay mood axes toward baseline over wall-clock hours
  apply_conversation_event_to_mood — no-op (axes unchanged by turn text/deltas; time recovery is separate)
  should_change_mood_label — inertia when switching to a trigger-suggested label
  apply_mood_nudge, next_mood_bias_after_turn, decay_mood_bias — mood ring / bias bookkeeping
  drift_toward — float drift helper toward a target
  halve_trigger_effect_numeric — repeat-trigger damping for aggregate

Module constants:
  VALID_MOODS, MOOD_NUDGE_ORDER, MOOD_OVERRIDE_PRIORITY, DEFAULT_BASELINE_* , etc.

Internal:
  _clamp_int, _halve_int_toward_zero, _clamp_float, _strip_json_fence — small utilities / LLM output cleanup
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Final

logger = logging.getLogger(__name__)

# Valid moods (must match schema CHECK on relationship_state.mood)
VALID_MOODS: Final[frozenset[str]] = frozenset(
    {"Calm", "Quiet", "Happy", "Irritated", "Playful", "Tired"}
)

# For mood_nudge: ordered from low to high "warmth / activation" (Irritated is override-only)
MOOD_NUDGE_ORDER: Final[list[str]] = ["Quiet", "Calm", "Tired", "Happy", "Playful"]

# When multiple triggers suggest a mood override, pick highest priority (more urgent beats subtle)
MOOD_OVERRIDE_PRIORITY: Final[dict[str, int]] = {
    "Irritated": 60,
    "Tired": 50,
    "Quiet": 40,
    "Playful": 35,
    "Happy": 30,
    "Calm": 20,
}

# Max total delta applied per long-term attribute in one turn (sum of triggers)
MAX_ABS_DELTA_PER_ATTR_PER_TURN: Final[int] = 3

# Max absolute mood nudge sum per turn
MAX_ABS_MOOD_NUDGE_PER_TURN: Final[int] = 3

# Max stored bias (steps along mood ring from stats baseline when no override / turn nudge)
MAX_MOOD_RECENT_BIAS: Final[int] = 3

# Max triggers returned by classifier / applied
MAX_TRIGGERS_PER_TURN: Final[int] = 3

# Positive stat bumps from triggers are multiplied by this fraction (floor) while mood is Irritated.
IRRITATED_POSITIVE_STAT_NUM: Final[int] = 1
IRRITATED_POSITIVE_STAT_DEN: Final[int] = 4

# If the classifier returns the same id again on the very next turn, skip it entirely (no stat/mood from that id).
TRIGGERS_SKIP_IF_ALSO_PREV_TURN: Final[frozenset[str]] = frozenset({"user_apology"})

# Mood-state v1 defaults and thresholds (state layer; prompt layer stays in companion/service/)
DEFAULT_BASELINE_ENERGY: Final[float] = 56.0
DEFAULT_BASELINE_IRRITATION: Final[float] = 16.0
DEFAULT_BASELINE_OUTWARDNESS: Final[float] = 46.0

# Time recovery rates per hour (toward baseline)
ENERGY_RECOVER_PER_HOUR: Final[float] = 4.0
IRRITATION_RECOVER_PER_HOUR: Final[float] = 5.0
OUTWARDNESS_RECOVER_PER_HOUR: Final[float] = 3.0

# Mood lock windows in minutes (inertia)
MIN_MOOD_MINUTES: Final[dict[str, float]] = {
    "Calm": 0.0,
    "Quiet": 2.0,
    "Happy": 2.0,
    "Playful": 2.0,
    "Tired": 10.0,
    "Irritated": 5.0,
}


@dataclass(frozen=True)
class TriggerEffect:
    trust: int = 0
    resonance: int = 0
    affection: int = 0
    openness: int = 0
    mood_override: str | None = None
    mood_nudge: int = 0


# Trigger id -> effect (each field uses only -3..3 except zeros)
TRIGGER_EFFECTS: Final[dict[str, TriggerEffect]] = {
    "user_gratitude": TriggerEffect(trust=1, resonance=1, affection=2),
    "user_apology": TriggerEffect(trust=2, resonance=1, affection=1, openness=1),
    "user_vulnerability_share": TriggerEffect(trust=2, resonance=1, affection=2, openness=2),
    "user_playful_banter": TriggerEffect(resonance=2, affection=1, mood_nudge=1),
    "user_compliment_to_bot": TriggerEffect(trust=1, resonance=2, affection=2, mood_override="Happy"),
    "user_mild_friction": TriggerEffect(trust=-1, resonance=-1),
    "user_harsh_rebuke": TriggerEffect(trust=-3, resonance=-2, affection=-2, openness=-1, mood_override="Irritated"),
    "user_dismissive_short": TriggerEffect(trust=-1, resonance=-2, affection=-1, openness=-1),
    "user_seeks_support": TriggerEffect(trust=1, resonance=2, affection=2, openness=1, mood_nudge=-1),
    "user_shares_joy": TriggerEffect(trust=1, resonance=2, affection=1, openness=1, mood_override="Happy"),
    "user_expresses_distress": TriggerEffect(trust=1, resonance=2, affection=2, mood_override="Quiet"),
    "assistant_comforting_tone": TriggerEffect(trust=1, resonance=2, affection=2, openness=1, mood_override="Calm"),
    "bonding_smalltalk": TriggerEffect(resonance=1, affection=1, openness=1),
    "boundary_push_or_test": TriggerEffect(trust=-1, openness=1),
    "affection_or_flirt_signal": TriggerEffect(trust=1, resonance=2, affection=3, openness=1, mood_override="Playful"),
    "reconciliation_or_repair": TriggerEffect(trust=2, resonance=2, affection=2, openness=1),
    "cold_or_hostile_exchange": TriggerEffect(trust=-2, resonance=-3, affection=-2, mood_override="Irritated"),
    "cooperative_problem_solving": TriggerEffect(trust=1, resonance=2, openness=2),
}


def trigger_ids_for_prompt() -> list[str]:
    return sorted(TRIGGER_EFFECTS.keys())


def _clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, x))


def _halve_int_toward_zero(x: int) -> int:
    """Halve magnitude for repeat-trigger decay (integers, toward zero)."""
    if x == 0:
        return 0
    s = 1 if x > 0 else -1
    return s * (abs(x) // 2)


def _clamp_float(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(x)))


def drift_toward(current: float, target: float, amount: float) -> float:
    """Move current toward target by amount (no overshoot)."""
    if amount <= 0:
        return float(current)
    if current < target:
        return min(current + amount, target)
    if current > target:
        return max(current - amount, target)
    return float(current)


def apply_time_recovery(state: dict[str, float], hours_elapsed: float) -> dict[str, float]:
    """Recover mood axes toward per-bot baselines based on elapsed time."""
    h = max(0.0, float(hours_elapsed))
    e = drift_toward(state["energy"], state["baseline_energy"], ENERGY_RECOVER_PER_HOUR * h)
    i = drift_toward(
        state["irritation"], state["baseline_irritation"], IRRITATION_RECOVER_PER_HOUR * h
    )
    o = drift_toward(
        state["outwardness"], state["baseline_outwardness"], OUTWARDNESS_RECOVER_PER_HOUR * h
    )
    state["energy"] = _clamp_float(e)
    state["irritation"] = _clamp_float(i)
    state["outwardness"] = _clamp_float(o)
    return state


def apply_conversation_event_to_mood(
    state: dict[str, float],
    *,
    trust_delta: int = 0,
    resonance_delta: int = 0,
    mood_override: str | None = None,
    mood_nudge: int = 0,
    trigger_ids: list[str] | None = None,
    user_message: str = "",
    interest_match: bool = False,
    user_short_reply: bool = False,
    long_dialogue: bool = False,
) -> dict[str, float]:
    """
    Mood axes are not modified per turn from text, stats deltas, or trigger metadata here.
    Stored ``mood`` label updates via trigger ``mood_override`` / ``mood_nudge`` in ``db._mood_label_and_changed``.
    Axes still evolve through ``apply_time_recovery`` on wall-clock time.
    Parameters after ``state`` are kept for call-site compatibility.
    """
    _ = (
        trust_delta,
        resonance_delta,
        mood_override,
        mood_nudge,
        trigger_ids,
        user_message,
        interest_match,
        user_short_reply,
        long_dialogue,
    )
    return state


def halve_trigger_effect_numeric(eff: TriggerEffect) -> TriggerEffect:
    """Same trigger again as last turn: soften numeric / nudge impact; keep mood_override."""
    return TriggerEffect(
        trust=_halve_int_toward_zero(eff.trust),
        resonance=_halve_int_toward_zero(eff.resonance),
        affection=_halve_int_toward_zero(eff.affection),
        openness=_halve_int_toward_zero(eff.openness),
        mood_override=eff.mood_override,
        mood_nudge=_halve_int_toward_zero(eff.mood_nudge),
    )


def decay_mood_bias(bias: int) -> int:
    """Move bias one step toward zero each turn (recent offset fades)."""
    b = int(bias)
    if b > 0:
        return b - 1
    if b < 0:
        return b + 1
    return 0


def next_mood_bias_after_turn(old_bias: int, mood_nudge: int, had_override: bool) -> int:
    """
    After resolving mood: decay stored bias, then add this turn's trigger nudge unless override won.
    """
    b = decay_mood_bias(int(old_bias))
    if had_override:
        return _clamp_int(b, -MAX_MOOD_RECENT_BIAS, MAX_MOOD_RECENT_BIAS)
    return _clamp_int(b + int(mood_nudge), -MAX_MOOD_RECENT_BIAS, MAX_MOOD_RECENT_BIAS)


def aggregate_trigger_effects(
    trigger_ids: list[str],
    *,
    previous_turn_trigger_ids: frozenset[str] | None = None,
) -> tuple[int, int, int, int, str | None, int]:
    """
    Sum effects for known trigger ids; clamp per-attribute totals and mood nudge.
    Triggers that also fired last turn use halved numeric / nudge (mood_override unchanged),
    except ids in TRIGGERS_SKIP_IF_ALSO_PREV_TURN which contribute nothing on a repeat (e.g. spam "对不起").
    Returns: dt, dr, da, do, mood_override_or_none, mood_nudge
    """
    prev = previous_turn_trigger_ids or frozenset()
    dt = dr = da = do = 0
    mood_candidates: list[str] = []
    mood_nudge = 0
    seen: set[str] = set()

    for tid in trigger_ids:
        if tid in seen:
            continue
        seen.add(tid)
        eff0 = TRIGGER_EFFECTS.get(tid)
        if eff0 is None:
            continue
        if tid in TRIGGERS_SKIP_IF_ALSO_PREV_TURN and tid in prev:
            continue
        eff = halve_trigger_effect_numeric(eff0) if tid in prev else eff0
        dt += eff.trust
        dr += eff.resonance
        da += eff.affection
        do += eff.openness
        if eff.mood_override and eff.mood_override in VALID_MOODS:
            mood_candidates.append(eff.mood_override)
        mood_nudge += eff.mood_nudge

    dt = _clamp_int(dt, -MAX_ABS_DELTA_PER_ATTR_PER_TURN, MAX_ABS_DELTA_PER_ATTR_PER_TURN)
    dr = _clamp_int(dr, -MAX_ABS_DELTA_PER_ATTR_PER_TURN, MAX_ABS_DELTA_PER_ATTR_PER_TURN)
    da = _clamp_int(da, -MAX_ABS_DELTA_PER_ATTR_PER_TURN, MAX_ABS_DELTA_PER_ATTR_PER_TURN)
    do = _clamp_int(do, -MAX_ABS_DELTA_PER_ATTR_PER_TURN, MAX_ABS_DELTA_PER_ATTR_PER_TURN)
    mood_nudge = _clamp_int(mood_nudge, -MAX_ABS_MOOD_NUDGE_PER_TURN, MAX_ABS_MOOD_NUDGE_PER_TURN)

    mood_override: str | None = None
    if mood_candidates:
        mood_override = max(mood_candidates, key=lambda m: MOOD_OVERRIDE_PRIORITY.get(m, 0))

    return dt, dr, da, do, mood_override, mood_nudge


def dampen_positive_stats_deltas_for_mood(
    dt: int,
    dr: int,
    da: int,
    do: int,
    *,
    mood: str,
) -> tuple[int, int, int, int]:
    """
    While Irritated, positive trust/resonance/affection/openness deltas from triggers are scaled down
    so brief apologies / small talk do not quickly raise stats before mood recovers. Negative deltas unchanged.
    """
    if (mood or "").strip() != "Irritated":
        return dt, dr, da, do
    den = IRRITATED_POSITIVE_STAT_DEN
    num = IRRITATED_POSITIVE_STAT_NUM
    if den <= 0:
        return dt, dr, da, do

    def scale(x: int) -> int:
        if x <= 0:
            return x
        return max(0, (x * num) // den)

    return scale(dt), scale(dr), scale(da), scale(do)


def apply_mood_nudge(current_mood: str, nudge: int) -> str:
    """Shift along MOOD_NUDGE_ORDER; Irritated stays unless nudge moves away from edge."""
    if nudge == 0:
        return current_mood if current_mood in VALID_MOODS else "Calm"
    if current_mood == "Irritated":
        # Recover slightly toward Quiet with positive nudge from user repair, etc.
        if nudge >= 2:
            return "Quiet"
        if nudge >= 1:
            return "Calm"
        return "Irritated"
    try:
        idx = MOOD_NUDGE_ORDER.index(current_mood)
    except ValueError:
        idx = MOOD_NUDGE_ORDER.index("Calm")
    new_idx = _clamp_int(idx + nudge, 0, len(MOOD_NUDGE_ORDER) - 1)
    return MOOD_NUDGE_ORDER[new_idx]


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text


def classify_triggers_llm(user_message: str, assistant_message: str) -> list[str]:
    """
    Ask the model for trigger IDs only (no scores). Returns at most MAX_TRIGGERS_PER_TURN ids.
    On any failure returns [].
    """
    if os.getenv("RELATIONSHIP_TRIGGERS_ENABLED", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return []

    ids = trigger_ids_for_prompt()
    listing = "\n".join(f"- {i}" for i in ids)

    payload = (
        "You classify ONE chat turn for relationship dynamics.\n"
        "You MUST output ONLY valid JSON, no markdown, no explanation.\n"
        "Schema: {\"triggers\":[\"trigger_id\",...]}\n"
        f"Allowed trigger_id values (use only these, or empty list):\n{listing}\n\n"
        "Rules:\n"
        f"- At most {MAX_TRIGGERS_PER_TURN} triggers.\n"
        "- Only choose a trigger if there is clear evidence in the messages.\n"
        "- Prefer fewer triggers when unsure.\n"
        "- Consider BOTH the user message and the assistant reply.\n\n"
        f"USER_MESSAGE:\n{user_message[:4000]}\n\n"
        f"ASSISTANT_MESSAGE:\n{assistant_message[:4000]}\n"
    )

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai not installed; skipping relationship trigger classification")
        return []

    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return []

    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip() or None
    client = OpenAI(api_key=key, base_url=base_url)
    default_model = "llama-3.3-70b-versatile" if base_url and "groq.com" in base_url else "gpt-4o-mini"
    model = (os.getenv("OPENAI_MODEL") or default_model).strip()

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "You output only compact JSON objects. Never output numbers for trust or mood scores.",
                },
                {"role": "user", "content": payload},
            ],
            max_tokens=256,
            temperature=0.2,
        )
    except Exception as e:
        logger.warning("relationship trigger LLM call failed: %s", e)
        return []

    choice = resp.choices and resp.choices[0]
    raw = (choice.message.content or "").strip() if choice and choice.message else ""
    if not raw:
        return []

    try:
        data: Any = json.loads(_strip_json_fence(raw))
    except json.JSONDecodeError:
        logger.warning("relationship trigger JSON parse failed: %s", raw[:200])
        return []

    if not isinstance(data, dict):
        return []
    tr = data.get("triggers")
    if not isinstance(tr, list):
        return []

    out: list[str] = []
    for x in tr[:MAX_TRIGGERS_PER_TURN]:
        if isinstance(x, str) and x in TRIGGER_EFFECTS and x not in out:
            out.append(x)
    return out


def should_change_mood_label(
    *,
    current_label: str,
    candidate_label: str,
    minutes_since_last_change: float,
    current_strength: float,
    candidate_strength: float,
    ignore_min_duration: bool = False,
) -> bool:
    """Use minimum duration and threshold margin to avoid mood thrashing."""
    if candidate_label == current_label:
        return False
    if not ignore_min_duration:
        min_minutes = MIN_MOOD_MINUTES.get(current_label, 0.0)
        if minutes_since_last_change < min_minutes:
            return False
    return (candidate_strength - current_strength) >= 3.0
