"""
HTTP load test against a local API pointed at the stress Neon DB.

Prerequisites:
  1) STRESS_DB_URL seeded (scripts/stress_seed.py)
  2) API running with DB_URL=STRESS_DB_URL

Usage:
  $env:STRESS_API_BASE = "http://127.0.0.1:8000"
  python scripts/stress_load.py
  python scripts/stress_load.py --workers 50 --duration 60
  python scripts/stress_load.py --include-llm   # also hits send-bot-message (costs $)
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from stress_common import (
    NUM_USERS,
    loadtest_password,
    loadtest_username,
)


@dataclass
class EndpointStats:
    ok: int = 0
    err: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, ok: bool, latency_ms: float) -> None:
        with self.lock:
            if ok:
                self.ok += 1
                self.latencies_ms.append(latency_ms)
            else:
                self.err += 1


@dataclass
class UserSession:
    username: str
    token: str
    bot_ids: list[int]


def _api_base() -> str:
    return (os.getenv("STRESS_API_BASE") or "http://127.0.0.1:8000").rstrip("/")


def _request_json(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, float, Any, str]:
    url = f"{_api_base()}{path}"
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            elapsed_ms = (time.perf_counter() - start) * 1000
            parsed: Any = None
            if raw:
                try:
                    parsed = json.loads(raw.decode())
                except json.JSONDecodeError:
                    parsed = raw.decode(errors="replace")
            return resp.status, elapsed_ms, parsed, ""
    except urllib.error.HTTPError as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        try:
            detail = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            detail = str(e)
        return e.code, elapsed_ms, None, detail
    except Exception as e:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return 0, elapsed_ms, None, str(e)


def _request(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, float, str]:
    status, ms, _, detail = _request_json(method, path, token=token, body=body, timeout=timeout)
    return status, ms, detail


def _login_all() -> list[UserSession]:
    password = loadtest_password()
    sessions: list[UserSession] = []
    for i in range(NUM_USERS):
        username = loadtest_username(i)
        status, _, payload, detail = _request_json(
            "POST",
            "/users/login",
            body={"username": username, "password": password, "remember_me": True},
        )
        if status != 200 or not isinstance(payload, dict):
            raise SystemExit(f"Login failed for {username}: HTTP {status} {detail}")
        token = str(payload["access_token"])

        status, _, bots_payload, detail = _request_json("GET", "/bots", token=token)
        if status != 200 or not isinstance(bots_payload, dict):
            raise SystemExit(f"GET /bots failed for {username}: HTTP {status} {detail}")
        bot_ids = [int(b["id"]) for b in bots_payload.get("bots", [])]
        if not bot_ids:
            raise SystemExit(f"No bots for {username}; run stress_seed.py first.")
        sessions.append(UserSession(username=username, token=token, bot_ids=bot_ids))
        print(f"  logged in {username} ({len(bot_ids)} bots)")
    return sessions


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_v = sorted(values)
    k = (len(sorted_v) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_v) - 1)
    if f == c:
        return sorted_v[f]
    return sorted_v[f] + (sorted_v[c] - sorted_v[f]) * (k - f)


def _print_stats(name: str, stats: EndpointStats) -> None:
    total = stats.ok + stats.err
    err_rate = (stats.err / total * 100) if total else 0.0
    lats = stats.latencies_ms
    print(f"\n{name}:")
    print(f"  requests: {total}  ok: {stats.ok}  err: {stats.err}  error_rate: {err_rate:.1f}%")
    if lats:
        print(f"  latency ms — p50: {_percentile(lats, 50):.0f}  p95: {_percentile(lats, 95):.0f}  max: {max(lats):.0f}")


def _worker(
    stop_at: float,
    sessions: list[UserSession],
    stats: dict[str, EndpointStats],
    include_llm: bool,
) -> None:
    rng = random.Random()
    while time.perf_counter() < stop_at:
        sess = rng.choice(sessions)
        bot_id = rng.choice(sess.bot_ids)
        choice = rng.random()
        if include_llm and choice < 0.1:
            endpoint = "send_bot_message"
            status, ms, _ = _request(
                "POST",
                "/chat/send-bot-message",
                token=sess.token,
                body={
                    "bot_id": bot_id,
                    "content": "load test ping",
                    "system_prompt": "You are a test bot.",
                },
            )
        elif choice < 0.5:
            endpoint = "history_bot"
            status, ms, _ = _request(
                "POST",
                "/chat/history/bot",
                token=sess.token,
                body={"bot_id": bot_id, "limit": 50},
            )
        elif choice < 0.8:
            endpoint = "list_bots"
            status, ms, _ = _request("GET", "/bots", token=sess.token)
        else:
            endpoint = "relationship"
            status, ms, _ = _request("GET", f"/bots/{bot_id}/relationship", token=sess.token)

        stats[endpoint].record(200 <= status < 300, ms)


def main() -> int:
    parser = argparse.ArgumentParser(description="HTTP load test for stress API.")
    parser.add_argument("--workers", type=int, default=50, help="Concurrent worker threads.")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds.")
    parser.add_argument(
        "--include-llm",
        action="store_true",
        help="Include POST /chat/send-bot-message (~10%% of requests; uses OpenAI).",
    )
    args = parser.parse_args()

    if args.workers < 1 or args.duration < 1:
        print("--workers and --duration must be >= 1", file=sys.stderr)
        return 2

    print(f"API base: {_api_base()}")
    print(f"Logging in {NUM_USERS} load-test users...")
    sessions = _login_all()

    stats: dict[str, EndpointStats] = {
        "list_bots": EndpointStats(),
        "history_bot": EndpointStats(),
        "relationship": EndpointStats(),
    }
    if args.include_llm:
        stats["send_bot_message"] = EndpointStats()

    stop_at = time.perf_counter() + args.duration
    print(f"\nRunning {args.workers} workers for {args.duration}s...")
    threads = [
        threading.Thread(
            target=_worker,
            args=(stop_at, sessions, stats, args.include_llm),
            daemon=True,
        )
        for _ in range(args.workers)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    print("\n=== Load test results ===")
    for name in ("list_bots", "history_bot", "relationship", "send_bot_message"):
        if name in stats:
            _print_stats(name, stats[name])

    total_err = sum(s.err for s in stats.values())
    total_ok = sum(s.ok for s in stats.values())
    print(f"\nTotal: {total_ok + total_err} requests, {total_err} errors")
    return 0 if total_err == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
