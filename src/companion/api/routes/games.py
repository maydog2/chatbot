from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from companion import service
from companion.api.deps import get_current_user_id, get_db_conn
from companion.api.schemas.games import GomokuRelationshipEventsIn
from companion.domain import gomoku_relationship
from companion.infra import db

router = APIRouter(prefix="/games", tags=["games"])


@router.post("/gomoku/relationship-events")
def gomoku_relationship_events(
    payload: GomokuRelationshipEventsIn,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """
    Apply Gomoku relationship events immediately (no chat turn).
    Returns updated relationship metrics for UI refresh.
    """
    evs = [str(x) for x in (payload.relationship_events or []) if str(x).strip()]
    pos = payload.position_summary
    # allow client to send only position_summary and skip explicit events
    if isinstance(pos, dict):
        pe = pos.get("events")
        if isinstance(pe, list):
            if "user_created_threat" in pe:
                evs.append("user_created_strong_threat")
            if "user_blocked_bot_threat" in pe:
                evs.append("user_blocked_bot_threat")
        mr = pos.get("match_result")
        if mr in ("user_win", "bot_win"):
            evs.append(str(mr))
    # dedupe
    seen: set[str] = set()
    evs = [e for e in evs if not (e in seen or seen.add(e))]
    eff = gomoku_relationship.aggregate_gomoku_relationship_effects(evs)
    try:
        db.apply_relationship_turn_deltas(
            user_id=user_id,
            bot_id=payload.bot_id,
            trust_delta=eff.trust,
            resonance_delta=eff.resonance,
            affection_delta=eff.affection,
            openness_delta=eff.openness,
            mood_override=eff.mood_override,
            mood_nudge=eff.mood_nudge,
            mood_force=True,
            user_message="",
            conn=conn,
        )
        return service.get_relationship_public(user_id, payload.bot_id, conn=conn)  # type: ignore
    except ValueError as e:
        detail = str(e)
        if detail == "bot not found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
