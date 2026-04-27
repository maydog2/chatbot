from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from companion import service
from companion.api.routes import auth, bots, chat, games, users
from companion.infra import db


def _cors_allow_origins() -> list[str]:
    """
    Resolve CORS allowlist.

    - Default: local frontend dev origins
    - Override/extend via env `CORS_ALLOW_ORIGINS`, comma-separated
      e.g. "http://localhost:3000,https://my-frontend.vercel.app"
    """
    default = ["http://localhost:3000", "http://127.0.0.1:3000"]
    raw = (os.getenv("CORS_ALLOW_ORIGINS") or "").strip()
    if not raw:
        return default
    parsed = [x.strip().rstrip("/") for x in raw.split(",") if x.strip()]
    return parsed or default


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
    db.ensure_bot_personality_column()
    service.ensure_companion_stderr_logging()
    try:
        yield
    finally:
        db.close_pool()


app = FastAPI(title="ChatBot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(bots.router)
app.include_router(chat.router)
app.include_router(games.router)