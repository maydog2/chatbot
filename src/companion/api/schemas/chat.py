from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class HistoryBotIn(BaseModel):
    bot_id: int = Field(gt=0)
    limit: int = Field(default=50, ge=1, le=200)


class GameChatTurnIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ActiveGameStateIn(BaseModel):
    """Client-held minigame state; when set with ephemeral_game, chat is not persisted."""

    type: Literal["gomoku"] = "gomoku"
    difficulty: Literal["relaxed", "serious"]
    current_turn: Literal["user", "bot"]
    bot_side: Literal["white", "black"]


class EphemeralGameIn(BaseModel):
    active_game: ActiveGameStateIn
    game_messages: list[GameChatTurnIn] = Field(default_factory=list)
    position_summary: dict[str, Any] | None = None
    # Optional relationship events produced by the client minigame UI.
    # Kept as strings so older clients can still talk to newer servers.
    relationship_events: list[str] = Field(default_factory=list)


class SendBotMessageIn(BaseModel):
    bot_id: int = Field(gt=0)
    content: str
    system_prompt: str
    trust_delta: int = Field(default=0, ge=-100, le=100)
    resonance_delta: int = Field(default=0, ge=-100, le=100)
    include_initiative_debug: bool = False
    ephemeral_game: EphemeralGameIn | None = None


class BuildPromptIn(BaseModel):
    bot_id: int = Field(gt=0)
    direction: str = ""


class ReplyIn(BaseModel):
    messages: list[dict[str, str]]  # [{"role": "user"|"assistant", "content": "..."}]
    system_prompt: str
