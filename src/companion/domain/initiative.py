"""
companion/domain/initiative.py — How “pushy” the bot should be this turn (initiative), from settings + context.

Public API:
  normalize_initiative(raw) — coerce bot setting to low | medium | high
  interest_match_user_message(...) — whether the user turn matches bot interests (used in scoring)
  effective_initiative_score(..., hostile_hint=None, warm_hint=None) — numeric 0–1; hostile/warm only from tone LLM hints
  effective_initiative_band(score) — bucket: very_low … very_high
  effective_initiative_snapshot(..., hostile_hint=None, warm_hint=None) — full dict (+ hostile_* / warm_* meta for debug)
  format_initiative_instruction(score) — paragraph appended to system prompt for this turn

Types / constants:
  InitiativeKey, InitiativeBand, EffectiveInitiativeSnapshot, BASE_SCORE, …

Internal:
  _hostile_meta, _warm_meta — map bool|None LLM hints to penalty/bump + source label
  _is_short_user_message — heuristic for short / passive turns
"""

from __future__ import annotations

from typing import Final, Literal, NotRequired, TypedDict

from . import interests

InitiativeKey = Literal["low", "medium", "high"]
InitiativeBand = Literal["very_low", "low", "moderate", "high", "very_high"]


class EffectiveInitiativeSnapshot(TypedDict):
    base: InitiativeKey
    score: float
    band: InitiativeBand
    interest_match: bool
    recent_user_messages: list[str]
    total_turns_in_window: int
    hostile_penalty: NotRequired[bool]
    hostile_source: NotRequired[str]
    warm_bump: NotRequired[bool]
    warm_source: NotRequired[str]

BASE_SCORE: Final[dict[InitiativeKey, float]] = {
    "low": 0.3,
    "medium": 0.5,
    "high": 0.75,
}


def normalize_initiative(raw: str | None) -> InitiativeKey:
    k = (raw or "medium").strip().lower()
    if k in ("low", "medium", "high"):
        return k  # type: ignore[return-value]
    return "medium"


def interest_match_user_message(
    primary: str | None, secondary: list[str], user_message: str
) -> bool:
    p = (primary or "").strip()
    sec = [str(x) for x in secondary if str(x).strip()]
    labels: list[str] = []
    if p:
        labels.append(interests.INTEREST_LABELS.get(p, p))
    for k in sec:
        labels.append(interests.INTEREST_LABELS.get(k, k))
    msg = (user_message or "").strip().lower()
    if not msg:
        return False
    return any(lab and lab.lower() in msg for lab in labels if lab)


def _is_short_user_message(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    return len(t) <= 12 or len(t.split()) <= 3


def _hostile_meta(hostile_hint: bool | None) -> tuple[bool, str]:
    """−0.12 when True; explicit False clears; None => no LLM signal, no penalty."""
    if hostile_hint is True:
        return True, "llm_yes"
    if hostile_hint is False:
        return False, "llm_no"
    return False, "unset"


def _warm_meta(warm_hint: bool | None) -> tuple[bool, str]:
    """+0.05 when True; explicit False or unset => no bump."""
    if warm_hint is True:
        return True, "llm_yes"
    if warm_hint is False:
        return False, "llm_no"
    return False, "unset"


def effective_initiative_score(
    *,
    base: InitiativeKey,
    trust: int,
    resonance: int,
    interest_match: bool,
    recent_user_messages: list[str],
    total_turns_in_window: int,
    hostile_hint: bool | None = None,
    warm_hint: bool | None = None,
) -> float:
    """
    Runtime score in ~[0, 1]. Higher => more willing to lead, extend, or revive conversation.
    """
    s = BASE_SCORE[base]

    t, r = int(trust), int(resonance)
    if t >= 65:
        s += 0.08
    elif t <= 35:
        s -= 0.1
    if r >= 65:
        s += 0.06
    elif r <= 35:
        s -= 0.08

    if interest_match:
        s += 0.1

    users = [x for x in recent_user_messages if (x or "").strip()]
    hostile_penalty, _ = _hostile_meta(hostile_hint)
    warm_bump, _ = _warm_meta(warm_hint)
    if users:
        if hostile_penalty:
            s -= 0.12
        if warm_bump:
            s += 0.05
        if len(users) >= 2 and _is_short_user_message(users[-1]) and _is_short_user_message(users[-2]):
            s -= 0.14

    if total_turns_in_window <= 2 and base == "high":
        s += 0.04
    elif total_turns_in_window >= 8:
        short_user_count = sum(1 for u in users[-3:] if _is_short_user_message(u))
        if short_user_count >= 2:
            s -= 0.08

    return max(0.05, min(0.95, s))


def effective_initiative_band(score: float) -> InitiativeBand:
    """Stable label for tests / logging; thresholds must match format_initiative_instruction."""
    if score < 0.36:
        return "very_low"
    if score < 0.48:
        return "low"
    if score < 0.62:
        return "moderate"
    if score < 0.78:
        return "high"
    return "very_high"


def effective_initiative_snapshot(
    *,
    base_raw: str | None,
    trust: int,
    resonance: int,
    primary_interest: str | None,
    secondary_interests: list[str],
    openai_messages: list[dict[str, str]],
    latest_user_content: str,
    hostile_hint: bool | None = None,
    warm_hint: bool | None = None,
) -> EffectiveInitiativeSnapshot:
    """
    Single place to compute score + band + inputs (for tests, API debug, or tooling).
    openai_messages: same shape as send_bot_message (roles user/assistant), including the latest user turn.
    """
    base = normalize_initiative(base_raw)
    recent_user_texts: list[str] = []
    for m in openai_messages:
        if m.get("role") == "user":
            recent_user_texts.append(str(m.get("content") or ""))
    interest_match = interest_match_user_message(
        primary_interest, secondary_interests, latest_user_content
    )
    total = len(openai_messages)
    recent_slice = recent_user_texts[-4:]
    hostile_penalty, hostile_source = _hostile_meta(hostile_hint)
    warm_bump, warm_source = _warm_meta(warm_hint)
    score = effective_initiative_score(
        base=base,
        trust=trust,
        resonance=resonance,
        interest_match=interest_match,
        recent_user_messages=recent_slice,
        total_turns_in_window=total,
        hostile_hint=hostile_hint,
        warm_hint=warm_hint,
    )
    return {
        "base": base,
        "score": score,
        "band": effective_initiative_band(score),
        "interest_match": interest_match,
        "recent_user_messages": recent_slice,
        "total_turns_in_window": total,
        "hostile_penalty": hostile_penalty,
        "hostile_source": hostile_source,
        "warm_bump": warm_bump,
        "warm_source": warm_source,
    }


def format_initiative_instruction(score: float) -> str:
    """Short English system add-on derived from effective score."""
    band = effective_initiative_band(score)
    if band == "very_low":
        return (
            "Conversational initiative (effective, this turn): very low — stay mostly reactive; answer what was asked; "
            "avoid opening new threads or broad invitations. "
            "Hard rule: do not end your reply with a new question to the user (including 'how about you', "
            "'what do you like', 'tell me about...', or Chinese 句末反问: 你呢、你最近…吗、有什么…吗、Master 你呢) "
            "unless one short clarification is strictly required to answer what they already asked. "
            "No rhetorical bounce-back; prefer a statement-only ending."
        )
    if band == "low":
        return (
            "Conversational initiative (effective, this turn): low — prefer following the user's lead; "
            "light extension only when it fits naturally; do not interview the user. "
            "Hard rule: avoid closing with a fresh invitation, new question, or 句末反问 (你呢、…吗)—especially after the user was short, "
            "vague, or disengaged; end on a concise statement unless they left a direct question unanswered."
        )
    if band == "moderate":
        return (
            "Conversational initiative (effective, this turn): moderate — you may occasionally extend or gently revive "
            "the thread when natural; not every turn needs a question, and not every reply should end with one."
        )
    if band == "high":
        return (
            "Conversational initiative (effective, this turn): high — you may help carry momentum: brief observations, "
            "natural bridges, or a single well-placed follow-up; still avoid machine-gun questions."
        )
    return (
        "Conversational initiative (effective, this turn): very high — you may actively keep the conversation moving "
        "with natural hooks or light new angles when appropriate; vary moves (not only questions)."
    )
