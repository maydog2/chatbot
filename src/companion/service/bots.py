"""
Bot creation and update service operations.
"""
from __future__ import annotations

from typing import Optional

import psycopg

from companion.domain import initiative as bot_initiative, interests
from companion.domain.personality import normalize_game_reply_style
from companion.infra import db

from .system_prompt import build_system_prompt_from_direction
from .users import effective_form_of_address


def _interests_from_bot(bot: dict) -> tuple[str | None, list[str]]:
    p = bot.get("primary_interest")
    p = None if p is None or not str(p).strip() else str(p).strip()
    s = bot.get("secondary_interests")
    if not isinstance(s, list):
        s = []
    return p, [str(x) for x in s]


def interests_tuple_for_prompt(bot: dict) -> tuple[str | None, list[str]]:
    """Public helper for API preview routes."""
    return _interests_from_bot(bot)


def create_bot(
    user_id: int,
    name: str,
    direction: str,
    *,
    primary_interest: str,
    secondary_interests: Optional[list[str]] = None,
    avatar_data_url: Optional[str] = None,
    form_of_address: Optional[str] = None,
    initiative: str = "medium",
    personality: str = "gentle",
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """Build system prompt, create a new session, create bot bound to that session. Returns bot dict."""
    resolved_name = (name or "My Bot").strip()
    if db.user_has_duplicate_bot_name(user_id, resolved_name, conn=conn):
        raise ValueError("a bot with this name already exists")
    av = (avatar_data_url or "").strip() or None
    if av and db.user_has_duplicate_bot_avatar(user_id, av, conn=conn):
        raise ValueError("a bot with this avatar already exists")

    foa = (form_of_address or "").strip()
    eff_addr = effective_form_of_address(form_of_address, user_id, conn=conn)
    p_n, s_n = interests.normalize_bot_interests(primary_interest, secondary_interests or [])
    ini = bot_initiative.normalize_initiative(initiative)
    sp = build_system_prompt_from_direction(
        direction or "a helpful, friendly companion",
        trust=40,
        resonance=30,
        affection=40,
        openness=30,
        mood="Calm",
        form_of_address=eff_addr,
        character_name=resolved_name,
        primary_interest=p_n,
        secondary_interests=s_n,
    )
    session_id = db.create_session(user_id, conn=conn)
    pers = normalize_game_reply_style(personality)
    bot_id = db.create_bot(
        user_id,
        session_id,
        name=resolved_name,
        system_prompt=sp,
        avatar_data_url=av,
        direction=direction or None,
        form_of_address=foa or None,
        primary_interest=p_n,
        secondary_interests=s_n,
        initiative=ini,
        personality=pers,
        conn=conn,
    )
    bot = db.get_bot(bot_id, conn=conn)
    assert bot is not None
    db.get_or_create_relationship(user_id, bot_id, conn=conn)
    return bot


def delete_bot(
    user_id: int,
    bot_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> bool:
    """Delete bot and its session (messages CASCADE). Returns True if deleted."""
    return db.delete_bot(bot_id, user_id, conn=conn)


def get_bots_by_user(
    user_id: int,
    conn: Optional[psycopg.Connection] = None,
) -> list[dict]:
    """List all bots for the user (from DB)."""
    return db.get_bots_by_user(user_id, conn=conn)


def update_bot(
    user_id: int,
    bot_id: int,
    *,
    name: str | None = None,
    direction: str | None = None,
    avatar_data_url: str | None = None,
    form_of_address: str | None = None,
    primary_interest: str | None = None,
    secondary_interests: list[str] | None = None,
    initiative: str | None = None,
    personality: str | None = None,
    update_name: bool = False,
    update_direction: bool = False,
    update_avatar: bool = False,
    update_form_of_address: bool = False,
    update_primary_interest: bool = False,
    update_secondary_interests: bool = False,
    update_initiative: bool = False,
    update_personality: bool = False,
    conn: Optional[psycopg.Connection] = None,
) -> dict:
    """
    Update bot fields and persist to DB.
    - If direction, form_of_address, or interests change, system_prompt is rebuilt using current relationship attributes.
    """
    bot = db.get_bot(bot_id, user_id=user_id, conn=conn)
    if bot is None:
        raise ValueError("bot not found")

    kwargs: dict[str, object] = {}
    if update_name:
        new_name_s = str(name or "").strip()
        if not new_name_s:
            raise ValueError("name must be non-empty")
        if db.user_has_duplicate_bot_name(user_id, new_name_s, exclude_bot_id=bot_id, conn=conn):
            raise ValueError("a bot with this name already exists")
        kwargs["name"] = name
    if update_avatar:
        if (
            avatar_data_url is not None
            and str(avatar_data_url).strip()
            and db.user_has_duplicate_bot_avatar(
                user_id, str(avatar_data_url).strip(), exclude_bot_id=bot_id, conn=conn
            )
        ):
            raise ValueError("a bot with this avatar already exists")
        kwargs["avatar_data_url"] = avatar_data_url

    update_interests = update_primary_interest or update_secondary_interests
    if update_interests:
        p_raw = primary_interest if update_primary_interest else bot.get("primary_interest")
        s_raw = (secondary_interests if update_secondary_interests else bot.get("secondary_interests")) or []
        if not isinstance(s_raw, list):
            s_raw = []
        p_stripped = (None if p_raw is None else str(p_raw).strip()) or None
        if not p_stripped:
            p_stripped = "self_growth"
        p_n, s_n = interests.normalize_bot_interests(p_stripped, list(s_raw))
        kwargs["primary_interest"] = p_n
        kwargs["secondary_interests"] = s_n

    if update_initiative:
        kwargs["initiative"] = bot_initiative.normalize_initiative(initiative)

    if update_personality:
        kwargs["personality"] = normalize_game_reply_style(personality)

    if update_direction or update_form_of_address or update_interests:
        rel = db.get_or_create_relationship(user_id, bot_id, conn=conn)
        if update_direction:
            new_dir = (direction or "").strip()
            kwargs["direction"] = new_dir or None
            dir_for_build = new_dir or "a helpful, friendly companion"
        else:
            dir_for_build = ((bot.get("direction") or "").strip() or "a helpful, friendly companion")
        if update_form_of_address:
            foa_stripped = ("" if form_of_address is None else str(form_of_address)).strip()
            kwargs["form_of_address"] = foa_stripped or None
            explicit_for_eff = foa_stripped
        else:
            explicit_for_eff = (bot.get("form_of_address") or "").strip()
        eff_addr = effective_form_of_address(explicit_for_eff or None, user_id, conn=conn)
        if update_interests:
            p_prompt = kwargs["primary_interest"]  # type: ignore[assignment]
            s_prompt = kwargs["secondary_interests"]  # type: ignore[assignment]
        else:
            p_prompt, s_prompt = _interests_from_bot(bot)
        char_label = str((name if update_name else bot.get("name")) or "").strip()
        sp = build_system_prompt_from_direction(
            dir_for_build,
            trust=rel["trust"],
            resonance=rel["resonance"],
            affection=rel["affection"],
            openness=rel["openness"],
            mood=rel["mood"],
            form_of_address=eff_addr,
            character_name=char_label,
            primary_interest=p_prompt,  # type: ignore[arg-type]
            secondary_interests=s_prompt,  # type: ignore[arg-type]
        )
        kwargs["system_prompt"] = sp

    updated = db.update_bot(bot_id, user_id, conn=conn, **kwargs)
    if updated is None:
        raise ValueError("bot not found")
    return updated
