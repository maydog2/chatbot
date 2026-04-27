from __future__ import annotations

from pydantic import BaseModel


class RegisterIn(BaseModel):
    display_name: str
    username: str
    password: str


class LoginIn(BaseModel):
    username: str
    password: str
    remember_me: bool = True
