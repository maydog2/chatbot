from companion.domain.personality import (
    ALL_GAME_REPLY_STYLES,
    normalize_game_reply_style,
)


def test_normalize_canonical():
    assert normalize_game_reply_style("playful") == "playful"
    assert normalize_game_reply_style("  COOL ") == "cool"


def test_normalize_legacy():
    assert normalize_game_reply_style("lively") == "playful"
    assert normalize_game_reply_style("cold") == "cool"
    assert normalize_game_reply_style("default") == "gentle"


def test_normalize_unknown_defaults_gentle():
    assert normalize_game_reply_style("nope") == "gentle"
    assert normalize_game_reply_style(None) == "gentle"


def test_all_styles_count():
    assert len(ALL_GAME_REPLY_STYLES) == 4
