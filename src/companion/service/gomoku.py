"""
Prompt helpers for Gomoku side-chat turns.
"""
from __future__ import annotations


def _gomoku_position_summary_for_prompt(raw: object) -> str:
    """Turn client JSON `position_summary` into a short English block for the LLM."""
    if not isinstance(raw, dict) or not raw:
        return ""
    lines: list[str] = []
    phase = raw.get("phase")
    if phase:
        lines.append(f"Phase: {phase}")
    ev = raw.get("eval")
    if ev:
        lines.append(f"Rough standing: {ev}")
    urgency = raw.get("urgency")
    if urgency:
        lines.append(f"Urgency: {urgency}")
    mc = raw.get("move_count")
    if mc is not None:
        lines.append(f"Stones on board: {mc}")
    lm = raw.get("last_move")
    lmb = raw.get("last_move_by")
    if isinstance(lm, dict) and lmb:
        lines.append(f"Last move: column {lm.get('x')}, row {lm.get('y')} by {lmb}")
    ct = raw.get("current_turn")
    if ct:
        lines.append(f"Side to move next (if not terminal): {ct}")
    threats = raw.get("threats")
    if isinstance(threats, dict):
        ut = threats.get("user") or []
        bt = threats.get("bot") or []
        if ut:
            lines.append(f"User shape threats (hints): {ut}")
        if bt:
            lines.append(f"Bot shape threats (hints): {bt}")
    wp = raw.get("winning_points")
    if isinstance(wp, dict):
        uw = wp.get("user") or []
        bw = wp.get("bot") or []
        if uw:
            lines.append(f"User immediate winning intersections (col,row): {uw}")
        if bw:
            lines.append(f"Bot immediate winning intersections (col,row): {bw}")
    evs = raw.get("events")
    if isinstance(evs, list) and evs:
        lines.append(f"Position events this turn vs last snapshot: {evs}")
    if raw.get("game_over"):
        lines.append("Game over: YES (client board state).")
        mr = raw.get("match_result")
        if mr:
            lines.append(f"Match result (user=black, bot=white): {mr}")
    else:
        lines.append("Game over: NO.")
    return "\n".join(lines)


def _gomoku_side_chat_reply_rules(raw: object) -> str:
    """Hard constraints so the LLM does not contradict the client board or invent moves."""
    d: dict = raw if isinstance(raw, dict) else {}
    parts: list[str] = [
        "Gomoku side-chat (obey in this reply):",
        "appears in the Board analysis as last move or in listed winning_points.",
        "- Tone: you are their opponent in the same game, not a teacher or child coach. Do NOT give tactical hints "
        "(e.g. 'there is a key point to end the game', 'watch this line'), do NOT pep-talk or patronize "
        "('keep it up', 'victory is in sight', '加油' style empty encouragement). React briefly in character—dry wit, "
        "grudging respect, playful sting, cool understatement—instead of explaining the position like a lesson.",
    ]
    if d.get("game_over"):
        parts.append(
            "- The client reports the match HAS ENDED. Do NOT say whose turn it is to play on the board. "
            "Do NOT describe your next move or ask what the user will play next."
        )
        mr = d.get("match_result")
        if mr == "bot_win":
            parts.append(
                "- Outcome: you (the character, white) won; the user (black) lost. Accept compliments without "
                "pretending the game is still in progress."
            )
        elif mr == "user_win":
            parts.append(
                "- Outcome: the user (black) won; you (white) lost. Be gracious; do not claim the game continues."
            )
        elif mr == "draw":
            parts.append("- Outcome: draw.")
    ev = d.get("eval")
    if not d.get("game_over") and ev in ("bot_winning", "user_winning"):
        parts.append(
            f"- Standing in analysis is '{ev}': do NOT call the position evenly matched, 50-50, or wide open unless you "
            "only soften tone without denying who is ahead."
        )
    if not d.get("game_over") and ev == "user_winning":
        parts.append(
            "- They have the upper hand: acknowledge pressure or credit without sounding like you are praising a student. "
            "No 'you played very well' essay unless it truly fits the persona; prefer short, sharp, or reluctant lines."
        )
    return "\n".join(parts)
