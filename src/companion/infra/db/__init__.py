"""
companion/infra/db — Postgres data layer (package facade).

Import: ``from companion.infra import db`` then ``db.create_user(...)``, etc.

Public API (aggregated from submodules; see each file for details):
  Pool / startup: DB_URL, init_pool, close_pool, ensure_relationship_mood_state_v1,
    ensure_bot_initiative_column, ensure_bot_personality_column
  Users: create_user, delete_user, get_display_name, get_user_id, get_password_hash,
    get_created_at, get_user_avatar_data_url, verify_password, update_user_password,
    update_user_display_name, update_user_avatar_data_url, get_user_field, update_user_field
  Auth tokens: create_auth_token, get_user_id_by_token_hash, revoke_token_by_hash
  Sessions: create_session, get_active_session_id, get_or_create_session, get_session_time, end_session
  Bots: create_bot, get_bot, get_bots_by_user, update_bot, delete_bot,
    user_has_duplicate_bot_name, user_has_duplicate_bot_avatar
  Messages: create_message, get_messages_by_session
  Relationship: get_or_create_relationship, update_relationship_state,
    refresh_relationship_mood_for_elapsed_time, apply_relationship_turn_deltas

Exposed for advanced callers / tests (treat as semi-internal):
  _pool — lazy alias of ``pool._pool`` (``from db import _pool`` at import time was stale after ``init_pool``)
  _MISSING — sentinel for update_bot optional kwargs
  _secondary_interests_list — coerce JSON/list to list[str] for bot rows

Implementation: pool.py, internal.py, users.py, sessions.py, bots.py, messages.py, relationship.py.
"""
from __future__ import annotations

from .bots import (
    create_bot,
    delete_bot,
    get_bot,
    get_bots_by_user,
    update_bot,
    user_has_duplicate_bot_avatar,
    user_has_duplicate_bot_name,
)
from .internal import _MISSING, _secondary_interests_list
from .messages import create_message, get_messages_by_session
from .pool import (
    DB_URL,
    close_pool,
    ensure_bot_initiative_column,
    ensure_bot_personality_column,
    ensure_relationship_mood_state_v1,
    init_pool,
)
from .relationship import (
    apply_relationship_turn_deltas,
    get_or_create_relationship,
    refresh_relationship_mood_for_elapsed_time,
    update_relationship_state,
)
from .sessions import (
    create_session,
    end_session,
    get_active_session_id,
    get_or_create_session,
    get_session_time,
)
from .users import (
    create_auth_token,
    create_user,
    delete_user,
    get_created_at,
    get_display_name,
    get_password_hash,
    get_user_avatar_data_url,
    get_user_field,
    get_user_id,
    get_user_id_by_token_hash,
    revoke_token_by_hash,
    update_user_avatar_data_url,
    update_user_display_name,
    update_user_field,
    update_user_password,
    verify_password,
)


def __getattr__(name: str):
    if name == "_pool":
        from . import pool as _pool_mod

        return _pool_mod._pool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DB_URL",
    "_MISSING",
    "_pool",
    "_secondary_interests_list",
    "apply_relationship_turn_deltas",
    "close_pool",
    "create_auth_token",
    "create_bot",
    "create_message",
    "create_session",
    "create_user",
    "delete_bot",
    "delete_user",
    "end_session",
    "ensure_bot_initiative_column",
    "ensure_bot_personality_column",
    "ensure_relationship_mood_state_v1",
    "get_active_session_id",
    "get_bot",
    "get_bots_by_user",
    "get_created_at",
    "get_display_name",
    "get_messages_by_session",
    "get_or_create_relationship",
    "get_or_create_session",
    "get_password_hash",
    "get_session_time",
    "get_user_avatar_data_url",
    "get_user_field",
    "get_user_id",
    "get_user_id_by_token_hash",
    "init_pool",
    "refresh_relationship_mood_for_elapsed_time",
    "revoke_token_by_hash",
    "update_bot",
    "update_relationship_state",
    "update_user_avatar_data_url",
    "update_user_display_name",
    "update_user_field",
    "update_user_password",
    "user_has_duplicate_bot_avatar",
    "user_has_duplicate_bot_name",
    "verify_password",
]
