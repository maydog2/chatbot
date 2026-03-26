import pytest

from companion.domain import interests


def test_normalize_primary_secondary_ok():
    p, s = interests.normalize_bot_interests("anime", ["gaming", "music"])
    assert p == "anime"
    assert s == ["gaming", "music"]


def test_primary_required():
    with pytest.raises(ValueError, match="primary_interest is required"):
        interests.normalize_bot_interests(None, [])
    with pytest.raises(ValueError, match="primary_interest is required"):
        interests.normalize_bot_interests("", [])
    with pytest.raises(ValueError, match="primary_interest is required"):
        interests.normalize_bot_interests("   ", ["gaming"])


def test_daily_life_cannot_be_primary():
    with pytest.raises(ValueError, match="cannot be used as primary"):
        interests.normalize_bot_interests("daily_life", [])


def test_secondary_max_three():
    with pytest.raises(ValueError, match="at most 3"):
        interests.normalize_bot_interests("anime", ["gaming", "music", "food", "travel"])


def test_secondary_must_not_repeat_primary():
    with pytest.raises(ValueError, match="must not include"):
        interests.normalize_bot_interests("anime", ["anime", "gaming"])


def test_prompt_block_empty_when_no_interests():
    assert interests.format_interests_for_prompt(None, []) == ""


def test_prompt_block_labels_and_flavor_no_raw_keys():
    t = interests.format_interests_for_prompt("anime", ["daily_life"])
    assert "Anime / ACG" in t
    assert "Daily life" in t
    assert "character dynamics" in t.lower() or "archetypes" in t.lower()
    assert "Subtle bias only" in t
    assert "outside your interest profile" in t
    assert "Standing rules" in t or "standing rules" in t
    # Keys should not appear as (anime) style debug
    assert " (anime)" not in t
    assert "daily_life" not in t


def test_dynamic_nudge_nonempty_when_interests():
    n = interests.format_interests_dynamic_nudge("hello there", "anime", [])
    assert n.startswith("[This turn]")
    assert "Interest relevance" in n
    assert "user-led" in n


def test_dynamic_nudge_empty_when_no_interests():
    assert interests.format_interests_dynamic_nudge("hi", None, []) == ""


def test_try_interest_user_message_maps_known_errors():
    assert (
        interests.try_interest_user_message(ValueError("invalid primary_interest: 'x'"))
        is not None
    )
    assert "not recognized" in interests.try_interest_user_message(
        ValueError("invalid primary_interest: 'x'")
    )
    assert interests.try_interest_user_message(ValueError("bot not found")) is None
