from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


InitiativeLevel = Literal["low", "medium", "high"]

GameReplyStyle = Literal["playful", "cool", "gentle", "tsundere"]


class CreateBotIn(BaseModel):
    name: str = "My Bot"
    direction: str = ""
    avatar_data_url: str | None = None
    form_of_address: str | None = None
    primary_interest: str
    secondary_interests: list[str] = Field(default_factory=list)
    initiative: InitiativeLevel = "medium"
    personality: GameReplyStyle = "gentle"


class UpdateBotIn(BaseModel):
    name: str | None = None
    direction: str | None = None
    avatar_data_url: str | None = None
    form_of_address: str | None = None
    primary_interest: str | None = None
    secondary_interests: list[str] | None = None
    initiative: InitiativeLevel | None = None
    personality: GameReplyStyle | None = None
