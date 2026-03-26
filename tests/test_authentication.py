from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from companion.infra import db


def test_authentication_lifecycle(user):
    """
    Lifecycle:
    - create token -> check valid -> revoke -> check invalid
    - also verify expired token is invalid
    """
    uid = int(user["id"])
    # Use a unique hash to avoid conflicts with other tests or residual auth_tokens within the same session.
    suffix = uuid.uuid4().hex[:12]
    token_hash = f"test_lifecycle_1_{suffix}"
    token_hash2 = f"test_lifecycle_2_{suffix}"

    # --- 1) create a valid token ---
    expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    token_id = db.create_auth_token(uid, token_hash, expires_at)
    assert isinstance(token_id, int)

    # --- 2) check valid ---
    got_uid = db.get_user_id_by_token_hash(token_hash)
    assert got_uid == uid

    # --- 3) revoke ---
    revoked = db.revoke_token_by_hash(token_hash)
    assert revoked is True

    # revoke again should be False (already revoked)
    revoked_again = db.revoke_token_by_hash(token_hash)
    assert revoked_again is False

    # --- 4) check invalid after revoke ---
    got_uid_after = db.get_user_id_by_token_hash(token_hash)
    assert got_uid_after is None

    # --- 5) expired token should be invalid ---
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    _ = db.create_auth_token(uid, token_hash2, expired_at)

    got_uid_expired = db.get_user_id_by_token_hash(token_hash2)
    assert got_uid_expired is None