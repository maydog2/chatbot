"""Unit tests for base / effective initiative scoring."""

from companion.domain import initiative as ini


def test_normalize_initiative_defaults_invalid():
    assert ini.normalize_initiative(None) == "medium"
    assert ini.normalize_initiative("  HIGH ") == "high"
    assert ini.normalize_initiative("nope") == "medium"


def test_effective_score_drops_with_low_trust():
    s = ini.effective_initiative_score(
        base="high",
        trust=20,
        resonance=50,
        interest_match=False,
        recent_user_messages=["ok", "sure"],
        total_turns_in_window=6,
    )
    assert s < ini.BASE_SCORE["high"]


def test_interest_match_bumps_score():
    base = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=False,
        recent_user_messages=["hello there"],
        total_turns_in_window=3,
    )
    bumped = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=True,
        recent_user_messages=["hello there"],
        total_turns_in_window=3,
    )
    assert bumped > base


def test_format_instruction_covers_range():
    low = ini.format_initiative_instruction(0.2)
    high = ini.format_initiative_instruction(0.9)
    assert "very low" in low.lower()
    assert "very high" in high.lower()


def test_effective_initiative_band_thresholds():
    assert ini.effective_initiative_band(0.35) == "very_low"
    assert ini.effective_initiative_band(0.36) == "low"
    assert ini.effective_initiative_band(0.47) == "low"
    assert ini.effective_initiative_band(0.48) == "moderate"
    assert ini.effective_initiative_band(0.77) == "high"
    assert ini.effective_initiative_band(0.78) == "very_high"


def test_effective_initiative_snapshot_matches_direct_score():
    last_user = "any food you recommend?"
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": last_user},
    ]
    snap = ini.effective_initiative_snapshot(
        base_raw="low",
        trust=40,
        resonance=60,
        primary_interest="food",
        secondary_interests=[],
        openai_messages=msgs,
        latest_user_content=last_user,
    )
    im = ini.interest_match_user_message("food", [], last_user)
    direct = ini.effective_initiative_score(
        base="low",
        trust=40,
        resonance=60,
        interest_match=im,
        recent_user_messages=["hi", last_user][-4:],
        total_turns_in_window=len(msgs),
    )
    assert snap["score"] == direct
    assert snap["band"] == ini.effective_initiative_band(direct)
    assert snap["base"] == "low"
    assert snap["interest_match"] is im
    assert snap["hostile_source"] == "unset"
    assert snap["hostile_penalty"] is False
    assert snap["warm_source"] == "unset"
    assert snap["warm_bump"] is False


def test_hostile_hint_true_penalizes_without_keywords():
    base = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=False,
        recent_user_messages=["whatever"],
        total_turns_in_window=3,
        hostile_hint=None,
    )
    penalized = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=False,
        recent_user_messages=["whatever"],
        total_turns_in_window=3,
        hostile_hint=True,
    )
    assert penalized < base


def test_hostile_hint_unset_ignores_rude_text_no_keyword_fallback():
    rude_last = "you are stupid"
    no_llm = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=False,
        recent_user_messages=[rude_last],
        total_turns_in_window=3,
        hostile_hint=None,
    )
    llm_says_hostile = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=False,
        recent_user_messages=[rude_last],
        total_turns_in_window=3,
        hostile_hint=True,
    )
    assert no_llm > llm_says_hostile


def test_warm_hint_true_bumps_score():
    base = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=False,
        recent_user_messages=["hey"],
        total_turns_in_window=3,
        warm_hint=None,
    )
    warm = ini.effective_initiative_score(
        base="medium",
        trust=50,
        resonance=50,
        interest_match=False,
        recent_user_messages=["hey"],
        total_turns_in_window=3,
        warm_hint=True,
    )
    assert warm > base
