"""Unit tests for trigger aggregation and DB application (no LLM)."""

import pytest
from companion.domain import relationship_triggers
from companion.infra import db
from companion import service


def test_aggregate_sums_and_clamps_per_attribute():
    # Duplicate ids in one list are de-duped (each trigger fires once per turn).
    ids = [
        "user_gratitude",
        "user_harsh_rebuke",
        "user_gratitude",
    ]
    dt, dr, da, do, mo, mn = relationship_triggers.aggregate_trigger_effects(ids)
    assert mo == "Irritated"
    assert mn == 0
    # One gratitude + harsh: t -2, r -1, a 0, o -1
    assert dt == -2
    assert dr == -1
    assert da == 0
    assert do == -1


def test_aggregate_duplicate_trigger_ids_count_once():
    dt, dr, da, do, _, _ = relationship_triggers.aggregate_trigger_effects(
        ["user_gratitude", "user_gratitude"]
    )
    assert (dt, dr, da, do) == (1, 1, 2, 0)


def test_aggregate_unknown_ids_ignored():
    assert relationship_triggers.aggregate_trigger_effects(["not_a_real_trigger"]) == (0, 0, 0, 0, None, 0)


def test_dampen_positive_while_irritated():
    assert relationship_triggers.dampen_positive_stats_deltas_for_mood(
        3, 2, 4, 1, mood="Irritated"
    ) == (0, 0, 1, 0)


def test_dampen_preserves_negative_and_skips_non_irritated():
    assert relationship_triggers.dampen_positive_stats_deltas_for_mood(
        -2, 3, 0, -1, mood="Irritated"
    ) == (-2, 0, 0, -1)
    assert relationship_triggers.dampen_positive_stats_deltas_for_mood(
        3, 3, 3, 3, mood="Calm"
    ) == (3, 3, 3, 3)


def test_consecutive_user_apology_contributes_nothing():
    prev = frozenset({"user_apology"})
    dt, dr, da, do, mo, mn = relationship_triggers.aggregate_trigger_effects(
        ["user_apology"],
        previous_turn_trigger_ids=prev,
    )
    assert (dt, dr, da, do) == (0, 0, 0, 0)
    assert mo is None
    assert mn == 0


def test_user_apology_after_other_trigger_still_counts_full():
    dt, dr, da, do, _, _ = relationship_triggers.aggregate_trigger_effects(
        ["user_apology"],
        previous_turn_trigger_ids=frozenset({"user_harsh_rebuke"}),
    )
    assert (dt, dr, da, do) == (2, 1, 1, 1)


def test_aggregate_clamps_each_attribute_at_three():
    ids = ["user_compliment_to_bot", "user_shares_joy", "user_gratitude"]
    dt, dr, da, do, _, _ = relationship_triggers.aggregate_trigger_effects(ids)
    assert dt == 3
    assert dr == 3
    assert da == 3
    assert do == 1


def test_aggregate_repeat_trigger_halves_numeric_delta():
    prev = frozenset({"user_gratitude"})
    dt, dr, da, do, _, _ = relationship_triggers.aggregate_trigger_effects(
        ["user_gratitude"],
        previous_turn_trigger_ids=prev,
    )
    assert (dt, dr, da, do) == (0, 0, 1, 0)


def test_aggregate_repeat_keeps_mood_override():
    prev = frozenset({"user_compliment_to_bot"})
    _, _, _, _, mo, mn = relationship_triggers.aggregate_trigger_effects(
        ["user_compliment_to_bot"],
        previous_turn_trigger_ids=prev,
    )
    assert mo == "Happy"
    assert mn == 0


def test_mood_nudge_moves_along_ring():
    assert relationship_triggers.apply_mood_nudge("Calm", 2) == "Happy"
    assert relationship_triggers.apply_mood_nudge("Happy", -1) == "Tired"


def test_apply_relationship_turn_deltas_independent_stats(user, monkeypatch):
    monkeypatch.setenv("RELATIONSHIP_TRIGGERS_ENABLED", "0")
    uid = user["id"]
    bot = service.create_bot(
        uid, "tbot", "friendly companion", primary_interest="anime", conn=None
    )
    bid = int(bot["id"])
    before = db.get_or_create_relationship(uid, bid)
    db.apply_relationship_turn_deltas(
        uid,
        bid,
        0,
        0,
        3,
        -2,
        mood_override=None,
        mood_nudge=1,
        conn=None,
    )
    after = db.get_or_create_relationship(uid, bid)
    assert after["trust"] == before["trust"]
    assert after["resonance"] == before["resonance"]
    assert after["affection"] == min(100, before["affection"] + 3)
    assert after["openness"] == max(0, before["openness"] - 2)
    assert after["mood"] in relationship_triggers.VALID_MOODS


def test_mood_state_recovery():
    st = {
        "energy": 20.0,
        "irritation": 80.0,
        "outwardness": 20.0,
        "baseline_energy": 56.0,
        "baseline_irritation": 16.0,
        "baseline_outwardness": 46.0,
    }
    out = relationship_triggers.apply_time_recovery(st, hours_elapsed=1.0)
    assert out["energy"] > 20.0
    assert out["irritation"] < 80.0
    assert out["outwardness"] > 20.0
def test_mood_inertia_respects_minimum_duration():
    assert not relationship_triggers.should_change_mood_label(
        current_label="Tired",
        candidate_label="Calm",
        minutes_since_last_change=1.0,
        current_strength=10.0,
        candidate_strength=20.0,
    )
