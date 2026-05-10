from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from companion import service

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 60
DEFAULT_EXEMPT_PATHS = {"/health", "/ready", "/docs", "/openapi.json", "/redoc"}
RATE_LIMIT_MESSAGES = {
    "login": "Too many login attempts. Please wait a moment and try again.",
    "register": "Too many account creation attempts. Please wait a moment and try again.",
    "chat_send": "You are sending messages too quickly. Please wait a moment before sending another message.",
    "bot_create": "You are creating bots too quickly. Please wait a moment and try again.",
    "profile_update": "You are updating settings too quickly. Please wait a moment and try again.",
    "default": "Too many requests. Please wait a moment and try again.",
}

_redis_client: Any | None = None

_INCR_WITH_TTL_SCRIPT = """
local count = redis.call("INCR", KEYS[1])
if count == 1 then
  redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
return {count, ttl}
"""


@dataclass(frozen=True)
class RateLimitConfig:
    enabled: bool
    redis_url: str | None
    default_per_minute: int
    login_per_minute: int
    register_per_minute: int
    chat_send_per_minute: int
    bot_create_per_minute: int
    profile_update_per_minute: int
    exempt_paths: set[str]
    trust_proxy_headers: bool
    log_secret: str


@dataclass(frozen=True)
class RateLimitIdentity:
    kind: str
    value: str


@dataclass(frozen=True)
class RateLimitDecision:
    path: str
    route_group: str
    identity: RateLimitIdentity
    limit: int


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    reset_epoch: int
    retry_after: int


def load_rate_limit_config() -> RateLimitConfig:
    return RateLimitConfig(
        enabled=_env_bool("RATE_LIMIT_ENABLED", default=False),
        redis_url=_env_str("RATE_LIMIT_REDIS_URL"),
        default_per_minute=_env_int("RATE_LIMIT_DEFAULT_PER_MINUTE", 60),
        login_per_minute=_env_int("RATE_LIMIT_LOGIN_PER_MINUTE", 5),
        register_per_minute=_env_int("RATE_LIMIT_REGISTER_PER_MINUTE", 3),
        chat_send_per_minute=_env_int("RATE_LIMIT_CHAT_SEND_PER_MINUTE", 10),
        bot_create_per_minute=_env_int("RATE_LIMIT_BOT_CREATE_PER_MINUTE", 5),
        profile_update_per_minute=_env_int("RATE_LIMIT_PROFILE_UPDATE_PER_MINUTE", 20),
        exempt_paths=_env_paths("RATE_LIMIT_EXEMPT_PATHS", DEFAULT_EXEMPT_PATHS),
        trust_proxy_headers=_env_bool("RATE_LIMIT_TRUST_PROXY_HEADERS", default=False),
        log_secret=_env_str("RATE_LIMIT_LOG_SECRET")
        or _env_str("AUTH_TOKEN_SECRET")
        or "rate-limit-log-secret",
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, config: RateLimitConfig | None = None) -> None:
        super().__init__(app)
        self._config = config or load_rate_limit_config()

    async def dispatch(self, request: Request, call_next) -> Response:
        config = self._config
        if not config.enabled or _is_exempt_request(request, config):
            return await call_next(request)

        decision = build_rate_limit_decision(request, config)
        result = await check_rate_limit(decision, config)
        if result is None:
            return await call_next(request)

        headers = _rate_limit_headers(result, include_retry_after=not result.allowed)
        if not result.allowed:
            return JSONResponse(
                status_code=429,
                content=rate_limit_error_body(decision),
                headers=headers,
            )

        response = await call_next(request)
        for name, value in headers.items():
            response.headers[name] = value
        return response


def build_rate_limit_decision(
    request: Request,
    config: RateLimitConfig,
) -> RateLimitDecision:
    path = normalized_path(request)
    ip_identity = RateLimitIdentity("ip", client_ip(request, config))

    if path == "/users/login":
        return RateLimitDecision(
            path=path,
            route_group="login",
            identity=ip_identity,
            limit=config.login_per_minute,
        )
    if path == "/users/register":
        return RateLimitDecision(
            path=path,
            route_group="register",
            identity=ip_identity,
            limit=config.register_per_minute,
        )

    user_id = user_id_from_authorization(request.headers.get("authorization"))
    user_or_ip_identity = (
        RateLimitIdentity("user", str(user_id))
        if user_id is not None
        else ip_identity
    )

    if path == "/chat/send-bot-message":
        return RateLimitDecision(
            path=path,
            route_group="chat_send",
            identity=user_or_ip_identity,
            limit=config.chat_send_per_minute,
        )

    if path == "/bots" and request.method.upper() == "POST":
        return RateLimitDecision(
            path=path,
            route_group="bot_create",
            identity=user_or_ip_identity,
            limit=config.bot_create_per_minute,
        )

    if (path == "/users/me" or path.startswith("/bots/")) and request.method.upper() == "PATCH":
        return RateLimitDecision(
            path=path,
            route_group="profile_update",
            identity=user_or_ip_identity,
            limit=config.profile_update_per_minute,
        )

    identity = user_or_ip_identity
    return RateLimitDecision(
        path=path,
        route_group="default",
        identity=identity,
        limit=config.default_per_minute,
    )


def rate_limit_error_body(decision: RateLimitDecision) -> dict[str, str]:
    return {
        "detail": "rate limit exceeded",
        "code": "rate_limit_exceeded",
        "route_group": decision.route_group,
        "message": RATE_LIMIT_MESSAGES.get(
            decision.route_group,
            RATE_LIMIT_MESSAGES["default"],
        ),
    }


async def check_rate_limit(
    decision: RateLimitDecision,
    config: RateLimitConfig,
) -> RateLimitResult | None:
    if decision.limit <= 0:
        logger.debug(
            "rate_limit_skipped_disabled",
            extra={
                "rate_limit": {
                    "path": decision.path,
                    "route_group": decision.route_group,
                }
            },
        )
        return None

    now = time.time()
    window_ttl = seconds_until_next_window(now)
    key = rate_limit_key(decision, now)
    try:
        client = redis_client(config)
        count_raw, ttl_raw = await client.eval(
            _INCR_WITH_TTL_SCRIPT,
            1,
            key,
            window_ttl,
        )
        count = int(count_raw)
        ttl = int(ttl_raw)
        if ttl <= 0:
            ttl = window_ttl
    except Exception as exc:
        log_rate_limit_warning(
            "rate_limit_redis_unavailable",
            decision=decision,
            config=config,
            error=exc,
        )
        return None

    remaining = max(0, decision.limit - count)
    reset_epoch = int(now + ttl)
    return RateLimitResult(
        allowed=count <= decision.limit,
        limit=decision.limit,
        remaining=remaining,
        reset_epoch=reset_epoch,
        retry_after=max(1, ttl),
    )


def rate_limit_key(decision: RateLimitDecision, now: float | None = None) -> str:
    timestamp = time.time() if now is None else now
    minute = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
        "%Y%m%d%H%M"
    )
    return (
        f"rl:{decision.identity.kind}:{decision.identity.value}:"
        f"{decision.route_group}:{minute}"
    )


def seconds_until_next_window(now: float | None = None) -> int:
    timestamp = time.time() if now is None else now
    return max(1, WINDOW_SECONDS - (int(timestamp) % WINDOW_SECONDS))


def user_id_from_authorization(authorization: str | None) -> int | None:
    if not authorization:
        return None

    scheme, sep, raw_token = authorization.partition(" ")
    if not sep or scheme.lower() != "bearer":
        return None

    raw_token = raw_token.strip()
    if not raw_token:
        return None

    try:
        return service.get_user_id_from_token(raw_token)
    except Exception:
        logger.debug("rate_limit_auth_token_parse_failed", exc_info=True)
        return None


def client_ip(request: Request, config: RateLimitConfig) -> str:
    if config.trust_proxy_headers:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            first_ip = forwarded_for.split(",", 1)[0].strip()
            if first_ip:
                return first_ip
        real_ip = request.headers.get("x-real-ip")
        if real_ip and real_ip.strip():
            return real_ip.strip()
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def hashed_identity(identity: RateLimitIdentity, config: RateLimitConfig) -> str:
    mac = hmac.new(
        key=config.log_secret.encode("utf-8"),
        msg=f"{identity.kind}:{identity.value}".encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return mac.hexdigest()[:16]


def log_rate_limit_warning(
    event: str,
    *,
    decision: RateLimitDecision,
    config: RateLimitConfig,
    error: Exception,
) -> None:
    logger.warning(
        event,
        extra={
            "rate_limit": {
                "path": decision.path,
                "route_group": decision.route_group,
                "identity_type": decision.identity.kind,
                "hashed_identity": hashed_identity(decision.identity, config),
                "error_type": type(error).__name__,
            }
        },
        exc_info=True,
    )


def redis_client(config: RateLimitConfig) -> Any:
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    if not config.redis_url:
        raise RuntimeError("RATE_LIMIT_REDIS_URL is not set")
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        raise RuntimeError("redis package is not installed") from exc
    _redis_client = Redis.from_url(config.redis_url, decode_responses=True)
    return _redis_client


async def close_rate_limit_redis() -> None:
    global _redis_client
    if _redis_client is None:
        return
    close = getattr(_redis_client, "aclose", None)
    if close is None:
        close = getattr(_redis_client, "close", None)
    if close is not None:
        result = close()
        if hasattr(result, "__await__"):
            await result
    _redis_client = None


def _rate_limit_headers(
    result: RateLimitResult,
    *,
    include_retry_after: bool,
) -> dict[str, str]:
    headers = {
        "X-RateLimit-Limit": str(result.limit),
        "X-RateLimit-Remaining": str(result.remaining),
        "X-RateLimit-Reset": str(result.reset_epoch),
    }
    if include_retry_after:
        headers["Retry-After"] = str(result.retry_after)
    return headers


def _is_exempt_request(request: Request, config: RateLimitConfig) -> bool:
    return request.method.upper() == "OPTIONS" or normalized_path(request) in config.exempt_paths


def normalized_path(request: Request) -> str:
    return request.url.path.rstrip("/") or "/"


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "invalid_int_env_var",
            extra={"rate_limit": {"env_var": name, "default": default}},
        )
        return default


def _env_str(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    value = raw.strip()
    return value or None


def _env_paths(name: str, default: set[str]) -> set[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return {_normalize_path_value(path) for path in default}
    return {_normalize_path_value(part) for part in raw.split(",") if part.strip()}


def _normalize_path_value(path: str) -> str:
    value = path.strip()
    if not value.startswith("/"):
        value = "/" + value
    return value.rstrip("/") or "/"