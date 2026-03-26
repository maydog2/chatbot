import uuid
import pytest
import psycopg
from companion.infra import db


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def user_id():
    uid = db.create_user(_uniq("dn"), _uniq("test_u"), "Abcdefg123!@#")
    yield uid
    try:
        db.delete_user(uid)
    except Exception:
        pass


@pytest.fixture()
def bot_id(user_id):
    sid = db.create_session(user_id)
    bid = db.create_bot(user_id, sid, "RelTest", "sp")
    return bid


def test_get_or_create_relationship_creates_and_is_idempotent(user_id, bot_id):
    r1 = db.get_or_create_relationship(user_id, bot_id)
    assert isinstance(r1["trust"], int)
    assert isinstance(r1["resonance"], int)
    assert 0 <= r1["trust"] <= 100
    assert 0 <= r1["resonance"] <= 100

    r2 = db.get_or_create_relationship(user_id, bot_id)
    assert r2["trust"] == r1["trust"] and r2["resonance"] == r1["resonance"]


def test_update_relationship_state_applies_deltas(user_id, bot_id):
    cur0 = db.get_or_create_relationship(user_id, bot_id)
    t0, r0 = cur0["trust"], cur0["resonance"]

    cur1 = db.update_relationship_state(user_id, bot_id, 5, -3)
    assert cur1["trust"] == max(0, min(100, t0 + 5))
    assert cur1["resonance"] == max(0, min(100, r0 - 3))

    cur2 = db.update_relationship_state(user_id, bot_id, -2, 10)
    assert cur2["trust"] == max(0, min(100, cur1["trust"] - 2))
    assert cur2["resonance"] == max(0, min(100, cur1["resonance"] + 10))


def test_update_relationship_state_clamps_to_bounds(user_id, bot_id):
    db.get_or_create_relationship(user_id, bot_id)

    cur_hi = db.update_relationship_state(user_id, bot_id, 10_000, 10_000)
    assert cur_hi["trust"] == 100
    assert cur_hi["resonance"] == 100

    cur_lo = db.update_relationship_state(user_id, bot_id, -10_000, -10_000)
    assert cur_lo["trust"] == 0
    assert cur_lo["resonance"] == 0


def test_relationship_raises_when_bot_not_found(user_id):
    missing_bid = 10**12
    with pytest.raises(ValueError, match="bot not found"):
        db.get_or_create_relationship(user_id, missing_bid)

    with pytest.raises(ValueError, match="bot not found"):
        db.update_relationship_state(user_id, missing_bid, 1, 1)


def test_refresh_relationship_mood_for_elapsed_time_drifts_axes(user_id, bot_id):
    db.get_or_create_relationship(user_id, bot_id)
    with psycopg.connect(db.DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE relationship_state
                SET irritation = 85,
                    last_mood_update_at = now() - interval '3 hours'
                WHERE bot_id = %s AND user_id = %s
                """,
                (bot_id, user_id),
            )
        conn.commit()
    before = float(db.get_or_create_relationship(user_id, bot_id)["irritation"])
    db.refresh_relationship_mood_for_elapsed_time(user_id, bot_id)
    after = float(db.get_or_create_relationship(user_id, bot_id)["irritation"])
    assert after < before
