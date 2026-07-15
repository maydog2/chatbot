# Stress testing (separate Neon DB)

Seed a **dedicated Neon branch/database** with load-test data, then run concurrent HTTP requests against a **local API** wired to that DB. Production Neon (`DB_URL`) and Render are not touched.

## What gets created

| Entity | Count | Notes |
|--------|-------|--------|
| Users | 20 | `loadtest_u00` … `loadtest_u19` |
| Bots / sessions | 200 | 10 bots per user (1 bot = 1 session) |
| Messages | 6200 | 31 per session |
| Relationship rows | 200 | one per bot |

## One-time setup

1. In [Neon Console](https://console.neon.tech), create a **branch** (or empty database) for stress testing.
2. Copy the **pooled** connection string.
3. In PowerShell (repo root), set env vars (do **not** commit these):

```powershell
$env:STRESS_DB_URL = "postgresql://...your-neon-stress-branch..."
$env:STRESS_LOADTEST_PASSWORD = "LoadTest!Abc123"   # optional; this is the default
$env:PYTHONPATH = "$PWD\src"
```

4. Initialize schema on the stress DB (once):

```powershell
$env:DB_URL = $env:STRESS_DB_URL
python -m companion.infra.init_db
```

## 1. Seed data

```powershell
python scripts/stress_seed.py
python scripts/stress_seed.py --force   # wipe loadtest_* users and re-seed
```

Scripts refuse to run if `STRESS_DB_URL` equals `DB_URL` (safety guard).

## 2. Run API against stress DB

In a **separate terminal**:

```powershell
$env:DB_URL = $env:STRESS_DB_URL
$env:AUTH_TOKEN_SECRET = "local-stress-secret"
$env:PYTHONPATH = "$PWD\src"
uvicorn companion.api:app --host 0.0.0.0 --port 8000
```

Optional: set `OPENAI_API_KEY` only if you plan to use `--include-llm` in the load script.

## 3. HTTP load test

```powershell
$env:STRESS_API_BASE = "http://127.0.0.1:8000"
python scripts/stress_load.py
python scripts/stress_load.py --workers 50 --duration 60
python scripts/stress_load.py --include-llm   # also hits send-bot-message (OpenAI cost)
```

Endpoints exercised (read-heavy by default):

- `GET /bots`
- `POST /chat/history/bot`
- `GET /bots/{id}/relationship`

Output includes request counts, error rate, and p50/p95 latency per endpoint.

## 4. Cleanup

```powershell
python scripts/stress_cleanup.py
python scripts/stress_cleanup.py --yes   # skip confirmation
```

Deletes all users whose username starts with `loadtest_` (CASCADE removes bots, sessions, messages, relationship rows).

## Sample login (after seed)

- Username: `loadtest_u00`
- Password: value of `STRESS_LOADTEST_PASSWORD` (default `LoadTest!Abc123`)

## What this proves / does not prove

- **Does**: query performance with ~6k messages; concurrent read API latency against Neon via local stack.
- **Does not**: Render production capacity unless you deliberately point production at the stress branch; LLM chat is off by default in the load script.
