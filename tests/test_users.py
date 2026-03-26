import uuid
import pytest
from companion.infra import db
from datetime import datetime, timedelta

# Random Username Generator
def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def test_create_user_returns_id():
    user_id = db.create_user(_uniq("dn"), _uniq("test_u"), "Abcdefg123!@#")
    assert isinstance(user_id, int)


def test_get_user_id_by_username(user):
    assert db.get_user_id(user["username"]) == user["id"]


def test_get_display_name_by_user_id(user):
    assert db.get_display_name(user["id"]) == user["display_name"]


def test_get_password_hash_exists_and_is_not_plaintext(user):
    ph = db.get_password_hash(user["id"])
    assert ph is not None
    assert isinstance(ph, str)
    assert ph != user["password"]  # must not store plaintext
    assert ph.startswith("$2")


def test_get_created_at_by_user_id(user):
    ts = db.get_created_at(user["id"])
    assert ts is not None
    assert isinstance(ts, datetime)

    now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
    assert ts <= now + timedelta(seconds=5)


def test_verify_password_true_and_false(user):
    assert db.verify_password(user["id"], user["password"]) is True
    assert db.verify_password(user["id"], "WrongPassword123!") is False


def test_update_user_password_changes_verification(user):
    new_pw = "NewPass456!@#"
    assert db.verify_password(user["id"], user["password"]) is True

    updated = db.update_user_password(user["id"], new_pw)
    assert updated is True

    assert db.verify_password(user["id"], user["password"]) is False
    assert db.verify_password(user["id"], new_pw) is True

def test_update_display_name(user):
    new_name = _uniq("dn_new")

    assert db.get_display_name(user["id"]) == user["display_name"]
    assert db.update_user_display_name(user["id"], new_name) is True
    assert db.get_display_name(user["id"]) == new_name

def test_delete_user_then_lookups_return_none(user):
    assert db.delete_user(user["id"]) is True
    assert db.get_display_name(user["id"]) is None
    assert db.get_password_hash(user["id"]) is None
    assert db.get_user_id(user["username"]) is None


# ---------------------------
# Boundary / Reverse Use Cases
# ---------------------------

def test_create_user_rejects_empty_display_name():
    with pytest.raises(ValueError):
        db.create_user("   ", _uniq("test_u"), "Abcdefg123!@#")


def test_create_user_rejects_empty_username():
    with pytest.raises(ValueError):
        db.create_user("maydog", "   ", "Abcdefg123!@#")


def test_create_user_duplicate_username_raises_value_error(user):
    with pytest.raises(ValueError) as e:
        db.create_user("dn2", user["username"], "Abcdefg123!@#")

    assert "username already exists" in str(e.value)


def test_verify_password_user_not_found_raises():
    with pytest.raises(ValueError):
        db.verify_password(-1, "whatever")


def test_update_user_password_empty_rejects(user):
    with pytest.raises(ValueError):
        db.update_user_password(user["id"], "")


def test_update_user_password_user_not_found_raises():
    with pytest.raises(ValueError):
        db.update_user_password(-1, "NewPass456!@#")


def test_update_display_name_empty_raises(user):
    with pytest.raises(ValueError):
        db.update_user_display_name(user["id"], "   ")


def test_delete_user_nonexistent_returns_false():
    assert db.delete_user(-1) is False