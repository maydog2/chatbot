from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from companion import service
from companion.api.deps import get_current_user_id, get_db_conn
from companion.api.schemas.chat import HistoryBotIn, SendBotMessageIn

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
    background_tasks: BackgroundTasks,
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
        # Background tasks use their own connection, so the chat turn must be visible first.
        conn.commit()  # type: ignore[attr-defined]
        background_tasks.add_task(
            service.run_memory_pipeline_for_turn,
            user_id=user_id,
            session_id=int(res["session_id"]),
            source_message_id=int(res["message_id"]),
            user_message=payload.content,
            assistant_response=str(res["assistant_reply"]),
        )
        return {**res, "display_name": display_name or ""}
    except ValueError as e:
        raise _value_error_to_http(e)
    except RuntimeError as e:
        msg = str(e)
        if "OPENAI_API_KEY is not set" in msg:
            raise HTTPException(status_code=503, detail="AI chat not configured (set OPENAI_API_KEY).")
        raise HTTPException(status_code=503, detail=msg)


@router.post("/end")
def end_session(user_id: int = Depends(get_current_user_id), conn=Depends(get_db_conn)):
    ended = service.end_current_session(user_id, conn=conn)  # type: ignore
    return {"ended": ended}
