import uuid
import pytest
from companion.infra import db

# Random Username Generator
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

def test_session_lifecycle(user_id):
    assert db.get_active_session_id(user_id) is None

    # Create session
    sid1 = db.get_or_create_session(user_id)
    assert isinstance(sid1, int)
    assert db.get_active_session_id(user_id) == sid1

    # Repeat get_or_create
    sid1_again = db.get_or_create_session(user_id)
    assert sid1_again == sid1

    # Test get_session_time
    started_at, ended_at = db.get_session_time(sid1)
    assert started_at is not None
    assert ended_at is None

    # End session
    assert db.end_session(sid1) is True
    assert db.end_session(sid1) is False
    assert db.get_active_session_id(user_id) is None

    # Create a new session
    sid2 = db.get_or_create_session(user_id)
    assert sid2 != sid1