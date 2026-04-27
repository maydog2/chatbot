from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class GomokuRelationshipEventsIn(BaseModel):
    bot_id: int = Field(gt=0)
    relationship_events: list[str] = Field(default_factory=list)
    position_summary: dict[str, Any] | None = None
