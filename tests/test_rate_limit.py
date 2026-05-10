from __future__ import annotations

from collections import defaultdict

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from companion.api import rate_limit

pytestmark = pytest.mark.no_db


class FakeRedis:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.counts: dict[str, int] = defaultdict(int)

    async def eval(self, script: str, numkeys: int, key: str, window_seconds: int):
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.counts[key] += 1
        return [self.counts[key], window_seconds]


@pytest.fixture(autouse=True)
def _auth_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test_secret_very_long_string")
    monkeypatch.setenv("AUTH_TOKEN_TTL_SECONDS", "3600")


def _config(
    *,
    default_per_minute: int = 60,
    login_per_minute: int = 5,
    register_per_minute: int = 3,
    chat_send_per_minute: int = 10,
    bot_create_per_minute: int = 5,
    profile_update_per_minute: int = 20,
    exempt_paths: set[str] | None = None,
    trust_proxy_headers: bool = False,
) -> rate_limit.RateLimitConfig:
    return rate_limit.RateLimitConfig(
        enabled=True,
        redis_url="redis://example.test:6379/0",
        default_per_minute=default_per_minute,
        login_per_minute=login_per_minute,
        register_per_minute=register_per_minute,
        chat_send_per_minute=chat_send_per_minute,
        bot_create_per_minute=bot_create_per_minute,
        profile_update_per_minute=profile_update_per_minute,
        exempt_paths=exempt_paths or set(rate_limit.DEFAULT_EXEMPT_PATHS),
        trust_proxy_headers=trust_proxy_headers,
        log_secret="test_rate_limit_log_secret",
    )


def _app(config: rate_limit.RateLimitConfig) -> FastAPI:
    test_app = FastAPI()
    test_app.add_middleware(rate_limit.RateLimitMiddleware, config=config)

    @test_app.post("/users/login")
    def login():
        return {"ok": True}

    @test_app.get("/users/me")
    def users_me():
        return {"ok": True}

    @test_app.get("/users/me/")
    def users_me_trailing_slash():
        return {"ok": True}

    @test_app.patch("/users/me")
    def update_me():
        return {"ok": True}

    @test_app.post("/bots")
    def create_bot():
        return {"ok": True}

    @test_app.patch("/bots/{bot_id}")
    def update_bot(bot_id: int):
        return {"ok": True, "bot_id": bot_id}

    @test_app.post("/chat/send-bot-message")
    def send_bot_message():
        return {"ok": True}

    @test_app.post("/chat/send-bot-message/")
    def send_bot_message_trailing_slash():
        return {"ok": True}

    @test_app.get("/health")
    def health():
        return {"ok": True}

    return test_app


@pytest.fixture()
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis()
    monkeypatch.setattr(rate_limit, "_redis_client", fake)
    return fake


def test_login_rate_limit_returns_429_headers(
    fake_redis: FakeRedis,
):
    with TestClient(_app(_config(login_per_minute=1))) as client:
        first = client.post("/users/login", json={"username": "missing", "password": "bad"})
        assert first.status_code == 200

        second = client.post("/users/login", json={"username": "missing", "password": "bad"})
        assert second.status_code == 429
        body = second.json()
        assert body["detail"] == "rate limit exceeded"
        assert body["code"] == "rate_limit_exceeded"
        assert body["route_group"] == "login"
        assert "login attempts" in body["message"]
        assert 1 <= int(second.headers["Retry-After"]) <= 60
        assert second.headers["X-RateLimit-Limit"] == "1"
        assert second.headers["X-RateLimit-Remaining"] == "0"
        assert int(second.headers["X-RateLimit-Reset"]) > 0


def test_default_route_with_parsed_user_id_uses_user_identity(
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(rate_limit, "user_id_from_authorization", lambda authorization: 123)

    headers = {"Authorization": "Bearer invalid-token-for-route-dependency"}
    with TestClient(_app(_config(default_per_minute=1))) as client:
        first = client.get("/users/me", headers=headers)
        assert first.status_code == 200

        second = client.get("/users/me", headers=headers)
        assert second.status_code == 429

    assert any("rl:user:123:default:" in key for key in fake_redis.counts)


def test_chat_send_route_has_separate_limit(fake_redis: FakeRedis):
    with TestClient(_app(_config(default_per_minute=100, chat_send_per_minute=1))) as client:
        first = client.post("/chat/send-bot-message")
        assert first.status_code == 200

        second = client.post("/chat/send-bot-message")
        assert second.status_code == 429
        body = second.json()
        assert body["code"] == "rate_limit_exceeded"
        assert body["route_group"] == "chat_send"
        assert "sending messages too quickly" in body["message"]

    assert any(":chat_send:" in key for key in fake_redis.counts)
    assert all(":default:" not in key for key in fake_redis.counts)


def test_chat_send_route_with_parsed_user_id_uses_user_identity(
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(rate_limit, "user_id_from_authorization", lambda authorization: 123)

    headers = {"Authorization": "Bearer invalid-token-for-route-dependency"}
    with TestClient(_app(_config(chat_send_per_minute=1))) as client:
        first = client.post("/chat/send-bot-message", headers=headers)
        assert first.status_code == 200

        second = client.post("/chat/send-bot-message", headers=headers)
        assert second.status_code == 429

    assert any("rl:user:123:chat_send:" in key for key in fake_redis.counts)


def test_bot_create_route_has_separate_limit(fake_redis: FakeRedis):
    with TestClient(_app(_config(default_per_minute=100, bot_create_per_minute=1))) as client:
        first = client.post("/bots")
        assert first.status_code == 200

        second = client.post("/bots")
        assert second.status_code == 429
        body = second.json()
        assert body["route_group"] == "bot_create"
        assert "creating bots too quickly" in body["message"]

    assert any(":bot_create:" in key for key in fake_redis.counts)
    assert all(":default:" not in key for key in fake_redis.counts)


def test_profile_update_routes_have_separate_limit(fake_redis: FakeRedis):
    with TestClient(_app(_config(default_per_minute=100, profile_update_per_minute=1))) as client:
        first = client.patch("/users/me")
        assert first.status_code == 200

        second = client.patch("/bots/123")
        assert second.status_code == 429
        body = second.json()
        assert body["route_group"] == "profile_update"
        assert "updating settings too quickly" in body["message"]

    assert any(":profile_update:" in key for key in fake_redis.counts)
    assert all(":default:" not in key for key in fake_redis.counts)


def test_default_route_uses_default_limit(fake_redis: FakeRedis):
    with TestClient(_app(_config(default_per_minute=1))) as client:
        first = client.get("/users/me")
        assert first.status_code == 200

        second = client.get("/users/me")
        assert second.status_code == 429
        body = second.json()
        assert body["code"] == "rate_limit_exceeded"
        assert body["route_group"] == "default"
        assert "Too many requests" in body["message"]

    assert any(":default:" in key for key in fake_redis.counts)


def test_zero_limit_disables_route_group(fake_redis: FakeRedis):
    with TestClient(_app(_config(chat_send_per_minute=0))) as client:
        for _ in range(3):
            response = client.post("/chat/send-bot-message")
            assert response.status_code == 200

    assert fake_redis.counts == {}


def test_authorization_scheme_is_case_insensitive(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rate_limit.service, "get_user_id_from_token", lambda raw_token: 123)

    assert rate_limit.user_id_from_authorization("bearer raw-token") == 123
    assert rate_limit.user_id_from_authorization("Bearer raw-token") == 123
    assert rate_limit.user_id_from_authorization("Bearer") is None
    assert rate_limit.user_id_from_authorization("BearerToken") is None


def test_redis_failure_fails_open_with_privacy_safe_warning(
    monkeypatch: pytest.MonkeyPatch,
):
    fake = FakeRedis(fail=True)
    monkeypatch.setattr(rate_limit, "_redis_client", fake)

    warnings: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        rate_limit.logger,
        "warning",
        lambda event, *, extra, **kwargs: warnings.append((event, extra["rate_limit"])),
    )
    raw_token = "raw-token-that-must-not-be-logged"
    with TestClient(_app(_config())) as client:
        response = client.get("/users/me", headers={"Authorization": f"Bearer {raw_token}"})

    assert response.status_code == 200
    event, structured = warnings[0]
    assert event == "rate_limit_redis_unavailable"
    assert structured["path"] == "/users/me"
    assert structured["route_group"] == "default"
    assert structured["identity_type"] == "ip"
    assert structured["hashed_identity"]
    assert structured["error_type"] == "RuntimeError"
    assert raw_token not in str(warnings)
    assert "testclient" not in str(warnings)


def test_exempt_health_path_does_not_touch_redis(fake_redis: FakeRedis):
    with TestClient(_app(_config())) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert fake_redis.counts == {}


def test_trailing_slash_paths_are_normalized(fake_redis: FakeRedis):
    with TestClient(_app(_config(chat_send_per_minute=1))) as client:
        first = client.post("/chat/send-bot-message/")
        assert first.status_code == 200

        second = client.post("/chat/send-bot-message/")
        assert second.status_code == 429

    assert any(":ip:" in key and ":chat_send:" in key for key in fake_redis.counts)


def test_trailing_slash_exempt_health_path_is_normalized(fake_redis: FakeRedis):
    with TestClient(_app(_config())) as client:
        response = client.get("/health/")

    assert response.status_code == 200
    assert fake_redis.counts == {}


def test_proxy_headers_ignored_when_not_trusted(fake_redis: FakeRedis):
    headers = {"X-Forwarded-For": "203.0.113.10"}
    with TestClient(_app(_config(default_per_minute=1))) as client:
        first = client.get("/users/me", headers=headers)
        assert first.status_code == 200

        second = client.get("/users/me", headers=headers)
        assert second.status_code == 429

    assert any("rl:ip:testclient:default:" in key for key in fake_redis.counts)
    assert all("203.0.113.10" not in key for key in fake_redis.counts)


def test_proxy_headers_used_when_trusted(fake_redis: FakeRedis):
    headers = {"X-Forwarded-For": "203.0.113.10, 198.51.100.20"}
    with TestClient(_app(_config(default_per_minute=1, trust_proxy_headers=True))) as client:
        first = client.get("/users/me", headers=headers)
        assert first.status_code == 200

        second = client.get("/users/me", headers=headers)
        assert second.status_code == 429

    assert any("rl:ip:203.0.113.10:default:" in key for key in fake_redis.counts)


def test_time_helpers_accept_zero_timestamp():
    decision = rate_limit.RateLimitDecision(
        path="/users/me",
        route_group="default",
        identity=rate_limit.RateLimitIdentity("user", "123"),
        limit=10,
    )

    assert rate_limit.seconds_until_next_window(0) == 60
    assert rate_limit.rate_limit_key(decision, 0).endswith(":197001010000")


def test_env_paths_are_normalized(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("RATE_LIMIT_EXEMPT_PATHS", "health,/docs/, /openapi.json")

    assert rate_limit._env_paths("RATE_LIMIT_EXEMPT_PATHS", set()) == {
        "/health",
        "/docs",
        "/openapi.json",
    }


def test_env_int_logs_invalid_values(monkeypatch: pytest.MonkeyPatch):
    warnings: list[tuple[str, dict]] = []
    monkeypatch.setenv("RATE_LIMIT_DEFAULT_PER_MINUTE", "not-an-int")
    monkeypatch.setattr(
        rate_limit.logger,
        "warning",
        lambda event, *, extra, **kwargs: warnings.append((event, extra["rate_limit"])),
    )

    assert rate_limit._env_int("RATE_LIMIT_DEFAULT_PER_MINUTE", 60) == 60
    assert warnings == [
        (
            "invalid_int_env_var",
            {"env_var": "RATE_LIMIT_DEFAULT_PER_MINUTE", "default": 60},
        )
    ]
