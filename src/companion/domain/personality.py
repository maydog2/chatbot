"""
companion/domain/personality.py — User-chosen game reply style (stored as ``bots.personality``).

Allowed values: playful, cool, gentle, tsundere. Default: gentle.
"""
from __future__ import annotations

GAME_REPLY_PLAYFUL = "playful"
GAME_REPLY_COOL = "cool"
GAME_REPLY_GENTLE = "gentle"
GAME_REPLY_TSUNDERE = "tsundere"

ALL_GAME_REPLY_STYLES: tuple[str, ...] = (
    GAME_REPLY_TSUNDERE,
    GAME_REPLY_PLAYFUL,
    GAME_REPLY_COOL,
    GAME_REPLY_GENTLE,
)

# Legacy DB / client values → canonical
_LEGACY_MAP: dict[str, str] = {
    "lively": GAME_REPLY_PLAYFUL,
    "cold": GAME_REPLY_COOL,
    "default": GAME_REPLY_GENTLE,
}


def normalize_game_reply_style(value: str | None) -> str:
    s = (value or "").strip().lower()
    if s in _LEGACY_MAP:
        return _LEGACY_MAP[s]
    if s in ALL_GAME_REPLY_STYLES:
        return s
    return GAME_REPLY_GENTLE
