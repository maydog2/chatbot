from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from companion import service
from companion.api.deps import get_current_user_id, get_db_conn
from companion.api.schemas.chat import BuildPromptIn, HistoryBotIn, ReplyIn, SendBotMessageIn
from companion.infra import db

router = APIRouter(prefix="/chat", tags=["chat"])


def _value_error_to_http(e: ValueError) -> HTTPException:
    detail = str(e)
    if detail == "bot not found":
        return HTTPException(status_code=404, detail=detail)
    return HTTPException(status_code=400, detail=detail)


@router.post("/history/bot")
def history_bot(
    payload: HistoryBotIn,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """Get message history for (user, bot_id)."""
    try:
        msgs = service.get_history_for_bot(
            user_id, payload.bot_id, limit=payload.limit, conn=conn  # type: ignore
        )
        return {"messages": msgs}
    except ValueError as e:
        raise _value_error_to_http(e)


@router.post("/send-bot-message")
def send_bot_message(
    payload: SendBotMessageIn,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """Save user message to DB, get assistant reply, save it, return reply + updated relationship. Session is per (user_id, bot_id)."""
    try:
        res = service.send_bot_message(
            user_id,
            payload.bot_id,
            payload.content,
            payload.system_prompt,
            trust_delta=payload.trust_delta,
            resonance_delta=payload.resonance_delta,
            include_initiative_debug=payload.include_initiative_debug,
            ephemeral_game=payload.ephemeral_game.model_dump(mode="json")
            if payload.ephemeral_game
            else None,
            conn=conn,  # type: ignore
        )
        display_name = service.get_display_name(user_id, conn=conn)  # type: ignore
        return {**res, "display_name": display_name or ""}
    except ValueError as e:
        raise _value_error_to_http(e)
    except RuntimeError as e:
        msg = str(e)
        if "OPENAI_API_KEY is not set" in msg:
            raise HTTPException(status_code=503, detail="AI chat not configured (set OPENAI_API_KEY).")
        raise HTTPException(status_code=503, detail=msg)


@router.post("/build-prompt")
def build_prompt(
    payload: BuildPromptIn,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """Build a full system prompt from the target bot and current relationship state."""
    bot = db.get_bot(payload.bot_id, user_id=user_id, conn=conn)  # type: ignore
    if bot is None:
        raise HTTPException(status_code=404, detail="bot not found")
    rel = db.get_or_create_relationship(user_id, payload.bot_id, conn=conn)  # type: ignore
    eff_addr = service.effective_form_of_address(bot.get("form_of_address"), user_id, conn=conn)  # type: ignore
    p_i, s_i = service.interests_tuple_for_prompt(bot)  # type: ignore[arg-type]
    system_prompt = service.build_system_prompt_from_direction(
        payload.direction,
        trust=rel["trust"],
        resonance=rel["resonance"],
        affection=rel["affection"],
        openness=rel["openness"],
        mood=rel["mood"],
        form_of_address=eff_addr,
        character_name=str(bot.get("name") or "").strip(),
        primary_interest=p_i,
        secondary_interests=s_i,
    )
    return {"system_prompt": system_prompt}


@router.post("/reply")
def reply(
    payload: ReplyIn,
    user_id: int = Depends(get_current_user_id),
):
    """Get an assistant reply for a custom bot (no DB save). Auth required."""
    try:
        assistant_reply = service.get_reply_for_custom_bot(
            payload.messages, payload.system_prompt
        )
        return {"assistant_reply": assistant_reply}
    except RuntimeError as e:
        msg = str(e)
        if "OPENAI_API_KEY is not set" in msg:
            raise HTTPException(status_code=503, detail="AI chat not configured (set OPENAI_API_KEY).")
        raise HTTPException(status_code=503, detail=msg)


@router.post("/end")
def end_session(user_id: int = Depends(get_current_user_id), conn=Depends(get_db_conn)):
    ended = service.end_current_session(user_id, conn=conn)  # type: ignore
    return {"ended": ended}
