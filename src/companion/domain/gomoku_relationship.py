"""
companion/domain/gomoku_relationship.py — Fixed relationship effects from Gomoku events.

This is intentionally small and deterministic: the client reports discrete events, we apply
fixed deltas and an optional mood hint using the existing mood label system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from . import relationship_triggers as rt


@dataclass(frozen=True)
class GomokuRelationshipEffect:
    trust: int = 0
    resonance: int = 0
    affection: int = 0
    openness: int = 0
    mood_override: str | None = None
    mood_nudge: int = 0


# Client/server event keys.
GOMOKU_RELATIONSHIP_EFFECTS: Final[dict[str, GomokuRelationshipEffect]] = {
    # User beats the bot: slight respect + connection, playful competitiveness.
    "user_win": GomokuRelationshipEffect(trust=1, resonance=1, mood_override="Playful"),
    # Bot beats the user: pride/happiness but not hostile.
    "bot_win": GomokuRelationshipEffect(mood_override="Happy"),
    # User restarts mid-game while behind: slight social penalty, annoyance.
    "user_restarted_while_losing": GomokuRelationshipEffect(
        resonance=-1, mood_override="Irritated"
    ),
    # User creates a strong threat: engaged / locked in.
    "user_created_strong_threat": GomokuRelationshipEffect(mood_override="Calm"),
    # User blocks bot's threat: focused / quiet.
    "user_blocked_bot_threat": GomokuRelationshipEffect(mood_override="Quiet"),
}


def aggregate_gomoku_relationship_effects(event_ids: list[str]) -> GomokuRelationshipEffect:
    """
    Sum deltas across events and pick the highest-priority mood_override.
    Unknown event IDs are ignored.
    """
    dt = dr = da = do = 0
    nudge = 0
    picked_mood: str | None = None
    picked_pri = -1

    for eid in event_ids:
        eff = GOMOKU_RELATIONSHIP_EFFECTS.get(str(eid))
        if eff is None:
            continue
        dt += int(eff.trust)
        dr += int(eff.resonance)
        da += int(eff.affection)
        do += int(eff.openness)
        nudge += int(eff.mood_nudge)
        mo = eff.mood_override
        if mo and mo in rt.VALID_MOODS:
            pri = int(rt.MOOD_OVERRIDE_PRIORITY.get(mo, 0))
            if pri > picked_pri:
                picked_mood = mo
                picked_pri = pri

    # Clamp numeric deltas using existing turn limits.
    cap = int(rt.MAX_ABS_DELTA_PER_ATTR_PER_TURN)
    dt = max(-cap, min(cap, dt))
    dr = max(-cap, min(cap, dr))
    da = max(-cap, min(cap, da))
    do = max(-cap, min(cap, do))

    ncap = int(rt.MAX_ABS_MOOD_NUDGE_PER_TURN)
    nudge = max(-ncap, min(ncap, nudge))

    return GomokuRelationshipEffect(
        trust=dt,
        resonance=dr,
        affection=da,
        openness=do,
        mood_override=picked_mood,
        mood_nudge=nudge,
    )

