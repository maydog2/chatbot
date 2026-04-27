"""
companion.service — public application service API.

The concrete business logic lives in focused modules under this package. This
file intentionally stays thin so callers can keep using:

    from companion import service
"""
from __future__ import annotations

from .auth_tokens import get_user_id_from_token, issue_access_token, logout
from .bots import (
    _interests_from_bot,
    create_bot,
    delete_bot,
    get_bots_by_user,
    interests_tuple_for_prompt,
    update_bot,
)
from .chat import (
    _initiative_tone_llm_enabled,
    _transcript_snippet_for_tone_llm,
    end_current_session,
    ensure_active_session,
    ensure_companion_stderr_logging,
    get_history_for_bot,
    get_reply_for_custom_bot,
    send_and_get_history,
    send_bot_message,
)
from .gomoku import _gomoku_position_summary_for_prompt, _gomoku_side_chat_reply_rules
from .relationships import (
    apply_relationship_triggers_after_turn,
    get_relationship,
    get_relationship_public,
)
from .reply_postprocess import (
    enforce_initiative_closing_question as _enforce_initiative_closing_question,
)
from .system_prompt import build_system_prompt_from_direction
from .users import (
    effective_form_of_address,
    get_display_name,
    get_me,
    login,
    register_user,
    update_me,
)

__all__ = [
    "apply_relationship_triggers_after_turn",
    "build_system_prompt_from_direction",
    "create_bot",
    "delete_bot",
    "effective_form_of_address",
    "end_current_session",
    "ensure_active_session",
    "ensure_companion_stderr_logging",
    "get_bots_by_user",
    "get_display_name",
    "get_history_for_bot",
    "get_me",
    "get_relationship",
    "get_relationship_public",
    "get_reply_for_custom_bot",
    "get_user_id_from_token",
    "interests_tuple_for_prompt",
    "issue_access_token",
    "login",
    "logout",
    "register_user",
    "send_and_get_history",
    "send_bot_message",
    "update_bot",
    "update_me",
    "_enforce_initiative_closing_question",
    "_gomoku_position_summary_for_prompt",
    "_gomoku_side_chat_reply_rules",
    "_initiative_tone_llm_enabled",
    "_interests_from_bot",
    "_transcript_snippet_for_tone_llm",
]
