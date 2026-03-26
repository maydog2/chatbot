"""
companion/api.py

Purpose:
- FastAPI HTTP layer for the Companion/ChatBot backend.
- Business logic in companion/service/; domain rules in companion/domain/; DB and LLM in companion/infra/.
- Postgres connection pool at app startup/shutdown (lifespan).
- Request-scoped DB transactions: one pooled connection per request, commit on success, rollback on error.

API endpoints (auth via Bearer token where marked *):
- POST /users/register, POST /users/login, POST /users/logout
- GET /users/me *, PATCH /users/me *  (display_name, avatar_data_url)
- POST /chat/history/bot *  (messages for a bot_id; each bot has its own session)
- POST /chat/send-bot-message *  (bot_id + optional trust/resonance deltas; relationship-aware prompt)
- POST /chat/build-prompt *, POST /chat/reply *, POST /chat/end *
- POST /bots *, GET /bots *, DELETE /bots/{bot_id} *, PATCH /bots/{bot_id} *  (name, direction, avatar)
- GET /bots/{bot_id}/relationship *  (trust, resonance, affection, openness, mood, display_name; per bot)

Request models include: RegisterIn, LoginIn, HistoryBotIn, SendBotMessageIn,
CreateBotIn, UpdateBotIn, BuildPromptIn, ReplyIn, UpdateMeIn, etc.
"""

from __future__ import annotations

import os
from typing import Generator, Literal
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import psycopg
from companion.domain import interests
from companion.infra import db
from companion import service
from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: login/token depend on this; fail fast if unset
    if not os.getenv("AUTH_TOKEN_SECRET") or not os.getenv("AUTH_TOKEN_SECRET").strip():
        raise RuntimeError(
            "AUTH_TOKEN_SECRET must be set (used for login/token). "
            "Example: set AUTH_TOKEN_SECRET=your-secret in env or .env."
        )
    db.init_pool()
    db.ensure_relationship_mood_state_v1()
    db.ensure_bot_initiative_column()
    service.ensure_companion_stderr_logging()
    try:
        yield
    finally:
        db.close_pool()

app = FastAPI(title="ChatBot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db_conn() -> Generator[psycopg.Connection, None, None]:
    """
    One connection per request:
    - borrow from pool
    - commit on success
    - rollback on error
    """
    if db._pool is None:
        raise RuntimeError("DB pool not initialized")

    with db._pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

def get_current_user_id(
    authorization: str | None = Header(default=None),
    conn: psycopg.Connection = Depends(get_db_conn),
) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    raw_token = authorization.removeprefix("Bearer ").strip()
    try:
        return service.get_user_id_from_token(raw_token, conn=conn)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


def get_optional_bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip()

# ---------- Request/Response models ----------
class RegisterIn(BaseModel):
    display_name: str
    username: str
    password: str


class LoginIn(BaseModel):
    username: str
    password: str
    remember_me: bool = True


class HistoryBotIn(BaseModel):
    bot_id: int
    limit: int = 50


class SendBotMessageIn(BaseModel):
    bot_id: int
    content: str
    system_prompt: str
    trust_delta: int = 0
    resonance_delta: int = 0
    include_initiative_debug: bool = False


InitiativeLevel = Literal["low", "medium", "high"]


class CreateBotIn(BaseModel):
    name: str = "My Bot"
    direction: str = ""
    avatar_data_url: str | None = None
    form_of_address: str | None = None
    primary_interest: str
    secondary_interests: list[str] = Field(default_factory=list)
    initiative: InitiativeLevel = "medium"


class UpdateBotIn(BaseModel):
    name: str | None = None
    direction: str | None = None
    avatar_data_url: str | None = None
    form_of_address: str | None = None
    primary_interest: str | None = None
    secondary_interests: list[str] | None = None
    initiative: InitiativeLevel | None = None


class BuildPromptIn(BaseModel):
    direction: str = ""


class ReplyIn(BaseModel):
    messages: list[dict[str, str]]  # [{"role": "user"|"assistant", "content": "..."}]
    system_prompt: str


class UpdateMeIn(BaseModel):
    display_name: str | None = None
    avatar_data_url: str | None = None


# ---------- Routes ----------
@app.post("/users/register")
def register(payload: RegisterIn, conn: psycopg.Connection = Depends(get_db_conn)):
    try:
        # pass conn down (requires your db/service functions accept conn and forward it)
        user_id = service.register_user(payload.display_name, payload.username, payload.password, conn=conn)  # type: ignore
        return {"user_id": user_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/users/login")
def login(payload: LoginIn, conn: psycopg.Connection = Depends(get_db_conn)):
    try:
        return service.issue_access_token(
            payload.username, payload.password, remember_me=payload.remember_me, conn=conn
        )
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid username or password")


@app.post("/users/logout")
def logout(
    conn: psycopg.Connection = Depends(get_db_conn),
    raw_token: str | None = Depends(get_optional_bearer_token),
):
    """Invalidate the current token (log out). Returns a 200 status code if no token exists or the token has expired."""
    if not raw_token:
        return {"revoked": False}
    revoked = service.logout(raw_token, conn=conn)  # type: ignore
    return {"revoked": revoked}


@app.get("/users/me")
def me(user_id: int = Depends(get_current_user_id), conn: psycopg.Connection = Depends(get_db_conn)):
    return service.get_me(user_id, conn=conn)  # type: ignore


@app.patch("/users/me")
def update_me_route(
    payload: UpdateMeIn,
    user_id: int = Depends(get_current_user_id),
    conn: psycopg.Connection = Depends(get_db_conn),
):
    fields = payload.model_fields_set
    try:
        return service.update_me(
            user_id,
            display_name=payload.display_name,
            avatar_data_url=payload.avatar_data_url,
            update_display_name="display_name" in fields,
            update_avatar="avatar_data_url" in fields,
            conn=conn,  # type: ignore
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/chat/history/bot")
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
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/chat/send-bot-message")
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
            conn=conn,  # type: ignore
        )
        display_name = service.get_display_name(user_id, conn=conn)  # type: ignore
        return {**res, "display_name": display_name or ""}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        msg = str(e)
        if "OPENAI_API_KEY is not set" in msg:
            raise HTTPException(status_code=503, detail="AI chat not configured (set OPENAI_API_KEY).")
        raise HTTPException(status_code=503, detail=msg)


@app.post("/bots")
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
            conn=conn,  # type: ignore
        )
        return bot
    except ValueError as e:
        detail = interests.try_interest_user_message(e) or str(e)
        raise HTTPException(status_code=400, detail=detail)
    except RuntimeError as e:
        msg = str(e)
        if "OPENAI_API_KEY is not set" in msg:
            raise HTTPException(status_code=503, detail="AI chat not configured (set OPENAI_API_KEY).")
        raise HTTPException(status_code=503, detail=msg)


@app.get("/bots")
def list_bots(
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """List all bots for the current user."""
    bots = service.get_bots_by_user(user_id, conn=conn)  # type: ignore
    return {"bots": bots}


@app.delete("/bots/{bot_id:int}")
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


@app.patch("/bots/{bot_id:int}")
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
    fields = payload.model_fields_set
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
            update_name="name" in fields,
            update_direction="direction" in fields,
            update_avatar="avatar_data_url" in fields,
            update_form_of_address="form_of_address" in fields,
            update_primary_interest="primary_interest" in fields,
            update_secondary_interests="secondary_interests" in fields,
            update_initiative="initiative" in fields,
            conn=conn,  # type: ignore
        )
        return bot
    except ValueError as e:
        detail = interests.try_interest_user_message(e) or str(e)
        raise HTTPException(status_code=400, detail=detail)


@app.post("/chat/build-prompt")
def build_prompt(
    payload: BuildPromptIn,
    user_id: int = Depends(get_current_user_id),
    conn=Depends(get_db_conn),
):
    """Build a full system prompt from the user's direction and current relationship state."""
    # Use user's first bot as context for relationship state.
    bots = service.get_bots_by_user(user_id, conn=conn)  # type: ignore
    if not bots:
        raise HTTPException(status_code=400, detail="no bots exist; create a bot first")
    bot_id = int(bots[0]["id"])
    rel = db.get_or_create_relationship(user_id, bot_id, conn=conn)  # type: ignore
    eff_addr = service.effective_form_of_address(bots[0].get("form_of_address"), user_id, conn=conn)  # type: ignore
    p_i, s_i = service.interests_tuple_for_prompt(bots[0])  # type: ignore[arg-type]
    system_prompt = service.build_system_prompt_from_direction(
        payload.direction,
        trust=rel["trust"],
        resonance=rel["resonance"],
        affection=rel["affection"],
        openness=rel["openness"],
        mood=rel["mood"],
        form_of_address=eff_addr,
        character_name=str(bots[0].get("name") or "").strip(),
        primary_interest=p_i,
        secondary_interests=s_i,
    )
    return {"system_prompt": system_prompt}


@app.post("/chat/reply")
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


@app.post("/chat/end")
def end_session(user_id: int = Depends(get_current_user_id), conn=Depends(get_db_conn)):
    ended = service.end_current_session(user_id, conn=conn)  # type: ignore
    return {"ended": ended}


@app.get("/bots/{bot_id:int}/relationship")
def relationship_for_bot(bot_id: int, user_id: int = Depends(get_current_user_id), conn: psycopg.Connection = Depends(get_db_conn)):
    rel = service.get_relationship_public(user_id, bot_id, conn=conn)  # type: ignore
    display_name = service.get_display_name(user_id, conn=conn)  # type: ignore
    return {**rel, "display_name": display_name or ""}