from __future__ import annotations

from pydantic import BaseModel


class UpdateMeIn(BaseModel):
    display_name: str | None = None
    avatar_data_url: str | None = None
