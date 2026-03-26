import uuid
import pytest
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


def test_message_lifecycle(user_id):
    sid = db.get_or_create_session(user_id)

    mid1 = db.create_message(user_id, sid, "user", "Hello!")
    mid2 = db.create_message(user_id, sid, "user", "World!")
    assert isinstance(mid1, int)
    assert isinstance(mid2, int)

    msgs2 = db.get_messages_by_session(sid, 10)
    by_id = {m["id"]: m["content"] for m in msgs2}
    assert by_id[mid1] == "Hello!"
    assert by_id[mid2] == "World!"
    assert 10**12 not in by_id

    mid3 = db.create_message(user_id, sid, "user", "Aha!")
    assert isinstance(mid3, int)

    msgs3 = db.get_messages_by_session(sid, 10)
    assert [m["content"] for m in msgs3] == ["Hello!", "World!", "Aha!"]


def test_create_message_invalid_role_raises(user_id):
    sid = db.get_or_create_session(user_id)
    with pytest.raises(ValueError, match="invalid role"):
        db.create_message(user_id, sid, "bad_role", "hi")


def test_create_message_empty_content_raises(user_id):
    sid = db.get_or_create_session(user_id)
    with pytest.raises(ValueError, match="content must be non-empty"):
        db.create_message(user_id, sid, "user", "   ")
