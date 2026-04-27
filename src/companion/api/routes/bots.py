from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from companion import service
from companion.api.deps import get_current_user_id, get_db_conn
from companion.api.schemas.bots import CreateBotIn, UpdateBotIn
from companion.domain import interests

router = APIRouter(prefix="/bots", tags=["bots"])


def _bot_value_error_to_http(e: ValueError) -> HTTPException:
    detail = interests.try_interest_user_message(e) or str(e)
    if str(e) == "bot not found":
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.post("")
def create_bot(
    payload: CreateBotIn,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """Create a new bot: build prompt, create session, create bot row. One bot = one session."""
    try:
        bot = service.create_bot(
            user_id,
            name=payload.name,
            direction=payload.direction,
            avatar_data_url=payload.avatar_data_url,
            form_of_address=payload.form_of_address,
            primary_interest=payload.primary_interest,
            secondary_interests=payload.secondary_interests,
            initiative=payload.initiative,
            personality=payload.personality,
            conn=conn,  # type: ignore
        )
        return bot
    except ValueError as e:
        raise _bot_value_error_to_http(e)
    except RuntimeError as e:
        msg = str(e)
        if "OPENAI_API_KEY is not set" in msg:
            raise HTTPException(status_code=503, detail="AI chat not configured (set OPENAI_API_KEY).")
        raise HTTPException(status_code=503, detail=msg)


@router.get("")
def list_bots(
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """List all bots for the current user."""
    bots = service.get_bots_by_user(user_id, conn=conn)  # type: ignore
    return {"bots": bots}


@router.delete("/{bot_id:int}")
def delete_bot_route(
    bot_id: int,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """Delete bot and its session (messages CASCADE)."""
    ok = service.delete_bot(user_id, bot_id, conn=conn)  # type: ignore
    if not ok:
        raise HTTPException(status_code=404, detail="bot not found")
    return {"deleted": True}


@router.patch("/{bot_id:int}")
def update_bot_route(
    bot_id: int,
    payload: UpdateBotIn,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """
    Update bot fields (rename / edit persona). Persists to DB.
    If direction is updated, system_prompt is rebuilt from direction + relationship metrics.
    """
    # Use exclude_unset so PATCH only applies keys present in the JSON body (reliable vs model_fields_set).
    patch = payload.model_dump(exclude_unset=True)
    try:
        bot = service.update_bot(
            user_id,
            bot_id,
            name=payload.name,
            direction=payload.direction,
            avatar_data_url=payload.avatar_data_url,
            form_of_address=payload.form_of_address,
            primary_interest=payload.primary_interest,
            secondary_interests=payload.secondary_interests,
            initiative=payload.initiative,
            personality=payload.personality,
            update_name="name" in patch,
            update_direction="direction" in patch,
            update_avatar="avatar_data_url" in patch,
            update_form_of_address="form_of_address" in patch,
            update_primary_interest="primary_interest" in patch,
            update_secondary_interests="secondary_interests" in patch,
            update_initiative="initiative" in patch,
            update_personality="personality" in patch,
            conn=conn,  # type: ignore
        )
        return bot
    except ValueError as e:
        raise _bot_value_error_to_http(e)


@router.get("/{bot_id:int}/relationship")
def relationship_for_bot(
    bot_id: int,
    user_id: int = Depends(get_current_user_id),
    conn: psycopg.Connection = Depends(get_db_conn),
):
    try:
        rel = service.get_relationship_public(user_id, bot_id, conn=conn)  # type: ignore
    except ValueError as e:
        raise _bot_value_error_to_http(e)
    display_name = service.get_display_name(user_id, conn=conn)  # type: ignore
    return {**rel, "display_name": display_name or ""}
