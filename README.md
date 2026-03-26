# ChatBot (Postgres + psycopg + pytest)

This project provides a small database-backed storage layer + service layer for a chatbot:
- Users / Sessions / Messages / Relationship state
- PostgreSQL (local Docker **or** hosted e.g. Neon)
- psycopg3 + connection pool
- pytest tests (auto reset schema)

## Quick start

### 1) Install dependencies

```powershell
cd path\to\ChatBot
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Environment variables

| Variable | Description | Example |
|----------|-------------|---------|
| `DB_URL` | PostgreSQL connection string | `postgresql://app:app_pw_123@127.0.0.1:5433/companion` |
| `AUTH_TOKEN_SECRET` | Secret for signing/validating login tokens (required) | `your-random-secret-string` |
| `AUTH_TOKEN_TTL_SECONDS` | Token expiry in seconds (optional) | `604800` (7 days) |
| `OPENAI_API_KEY` | API key for AI chat. Use **Groq key** (from [console.groq.com](https://console.groq.com)) when using Groq. | `gsk_...` (Groq) |
| `OPENAI_BASE_URL` | API base URL. Set to Groq URL when using Groq. | `https://api.groq.com/openai/v1` (Groq) |
| `OPENAI_MODEL` | Model name. OpenAI default (chat): `gpt-4o` if unset. Groq: `llama-3.3-70b-versatile`. | optional |
| `CHATBOT_LOG_INITIATIVE` | If `1` / `true` / `yes` / `on`, log effective initiative on each bot reply (stderr, e.g. `INFO:companion.service:initiative bot_id=...`). | `1` |
| `CHATBOT_INITIATIVE_TONE_LLM` | If `1` / `true` / `yes` / `on`, one small LLM call per turn classifies the latest user turn as **hostile** and/or **warm** (thanks, apology, de-escalation, repair) using recent transcript for context—used only for initiative nudges (not moderation). No keyword fallback. | unset (off) |
| `CHATBOT_INITIATIVE_HOSTILITY_LLM` | Legacy alias for `CHATBOT_INITIATIVE_TONE_LLM` (same behavior). | optional |
| `CHATBOT_TONE_MODEL` | Model for that classifier (default `gpt-4o-mini`). `CHATBOT_HOSTILITY_MODEL` is accepted as an alias. | optional |

**Neon / hosted Postgres:** put `DB_URL` in a repo-root `.env` file (see `.env.example`) so you do not paste secrets into the shell history. The app loads `.env` on startup (`python-dotenv`; skipped automatically under `pytest`). Use the **pooled** connection string from Neon and keep `sslmode=require`. If you hit TLS / channel-binding errors on Windows, try removing `channel_binding=require` from the URL (Neon’s dashboard often offers variants).

Example (PowerShell):

```powershell
$env:DB_URL = "postgresql://app:app_pw_123@127.0.0.1:5433/companion"
$env:AUTH_TOKEN_SECRET = "your-secret-at-least-32-chars"
```

### 3) Run the API

Set env vars **in the same terminal** where you run uvicorn, then start the API. No code change needed: use Groq by setting the three variables below.

**Using Groq (recommended, free tier):**

```powershell
$env:PYTHONPATH = "$PWD\src"
$env:AUTH_TOKEN_SECRET = "your-secret-at-least-32-chars"
$env:OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
$env:OPENAI_API_KEY = "gsk_your-groq-api-key"
$env:OPENAI_MODEL = "llama-3.3-70b-versatile"
.\.venv\Scripts\python.exe -m uvicorn companion.api:app --reload --host 0.0.0.0 --port 8000
```

Replace `gsk_your-groq-api-key` with your real key from [Groq Console → API Keys](https://console.groq.com/keys).

**Using OpenAI:** set `$env:OPENAI_API_KEY = "sk-proj-..."` (or `sk-...`) and do **not** set `OPENAI_BASE_URL` (or leave it empty). Default chat model is `gpt-4o`. Optional: `$env:OPENAI_MODEL = "gpt-4o-mini"` to save cost.

If a **Groq** `OPENAI_BASE_URL` is still set in your environment (e.g. from an old session) while you use an OpenAI `sk-` key, the app **overrides** it with `https://api.openai.com/v1`. (The OpenAI Python SDK treats `base_url=None` as “read `OPENAI_BASE_URL` from the environment again”, so we pass an explicit OpenAI host; otherwise requests would still go to Groq and return `401 invalid_api_key`.)

If the venv is already activated (`.\.venv\Scripts\Activate.ps1`), you can run: `uvicorn companion.api:app --reload --host 0.0.0.0 --port 8000`

API docs: http://127.0.0.1:8000/docs

---

## Frontend (Next.js + React + TypeScript)

Frontend lives in `frontend/`. Start the backend API first, then run the frontend.

```powershell
cd frontend
copy .env.local.example .env.local
# If API is not on port 8000, edit NEXT_PUBLIC_API_URL in .env.local
npm install
npm run dev
```

Open http://localhost:3000 to register, login, send messages, view history, end session, and logout.

---

## Run backend and frontend (two terminals)

Use **two** terminal windows: one for the API, one for the frontend.

### Terminal 1 – Backend (API)

**Where to set API key:** in this same terminal, **before** the last line (uvicorn). Run the `$env:...` lines one by one, and replace `gsk_your-groq-api-key` with your key from [Groq Console](https://console.groq.com/keys).

```powershell
cd path\to\ChatBot
$env:PYTHONPATH = "$PWD\src"
$env:AUTH_TOKEN_SECRET = "your-secret-at-least-32-chars"
$env:OPENAI_BASE_URL = "https://api.groq.com/openai/v1"
$env:OPENAI_API_KEY = "gsk_your-groq-api-key"
$env:OPENAI_MODEL = "llama-3.3-70b-versatile"
.\.venv\Scripts\python.exe -m uvicorn companion.api:app --reload --host 0.0.0.0 --port 8000
```

Leave this running. You should see: `Uvicorn running on http://0.0.0.0:8000`.

### Terminal 2 – Frontend (Next.js)

**First time only** (install deps and env):

```powershell
cd path\to\ChatBot\frontend
copy .env.local.example .env.local
cmd /c "npm install"
```

Then start the dev server:

```powershell
cd path\to\ChatBot\frontend
cmd /c "npm run dev"
```

If PowerShell allows scripts (`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`), you can use `npm install` and `npm run dev` instead of `cmd /c "..."`.

Leave this running. You should see: `Ready in ...` and `http://localhost:3000`.

### Use the app

- Frontend: http://localhost:3000  
- API docs: http://127.0.0.1:8000/docs  

**Note:** Backend must be running before you register or login in the frontend. Postgres must be reachable at `DB_URL` (Docker `pg-companion` on port 5433, or Neon, etc.).

---

## Database Setup

### Neon (no local Docker)

1. Copy `.env.example` to `.env` in the repo root.
2. Set `DB_URL` to your Neon connection string (prefer the **pooler** host for the API).
3. Apply the base schema once:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m companion.infra.init_db
```

(`init_db` reads `DB_URL` from `.env` when you omit `--db`.)

### 1) Start Postgres (Docker)

This repo assumes you have a running container named `pg-companion` with port mapping `5433:5432`.

If you don't have one yet, here is a simple way to start it:
```powershell
docker run --name pg-companion -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app_pw_123 -e POSTGRES_DB=companion -p 5433:5432 -d postgres:16
```

Verify:
```powershell
docker ps
```

### 2) Create test database inside Docker (one-time)

In this project, the test database is `companion_test`.

```powershell
docker exec -it pg-companion psql -U app -d companion -c "CREATE DATABASE companion_test;"
docker exec -it pg-companion psql -U app -d companion -c "GRANT ALL PRIVILEGES ON DATABASE companion_test TO app;"
```

Verify it exists:
```powershell
docker exec -it pg-companion psql -U app -d companion -c "\l"
```

### 3) Initialize schema (optional)

- Dev DB (safe: create objects if missing):
```powershell
$env:PYTHONPATH = "$PWD\src"
python -m companion.infra.init_db --db "postgresql://app:app_pw_123@127.0.0.1:5433/companion"
```

- Test DB (DANGER: drops tables + recreates everything):
```powershell
$env:PYTHONPATH = "$PWD\src"
python -m companion.infra.init_db --db "postgresql://app:app_pw_123@127.0.0.1:5433/companion_test" --reset
```

> ⚠️ `--reset` will DROP tables. Use it only for dev/test databases.

**If you have an existing database** created before the bots table existed, run the migration (creates `bots` table; removes `bot_id` from `sessions` if present). From the repo root (with `psql` in PATH):

```powershell
psql $env:DB_URL -f src/companion/migrations/001_add_bot_id_to_sessions.sql
```

If your DB was created before **form of address** (how the bot refers to you) existed, add the column:

```powershell
psql $env:DB_URL -f src/companion/migrations/006_bot_form_of_address.sql
```

If an old database is missing a **unique username** index (normally already present in `schema.sql` / `reset.sql`):

```powershell
psql $env:DB_URL -f src/companion/migrations/007_users_username_unique.sql
```

To delete a specific user row by id (removes their bots first), e.g. user `2`:

```powershell
python scripts/delete_user_by_id.py 2
```

If your DB predates **bot interests** (primary + secondary JSON on `bots`):

```powershell
psql $env:DB_URL -f src/companion/migrations/008_bot_interests.sql
```

If some bots still have **NULL** `primary_interest` (older data), backfill a default primary:

```powershell
psql $env:DB_URL -f src/companion/migrations/009_backfill_bot_primary_interest.sql
```

If your DB predates the **mood state v1** update (energy / irritation / outwardness axes + baseline recovery):

```powershell
psql $env:DB_URL -f src/companion/migrations/010_relationship_mood_state_v1.sql
```

On startup, the FastAPI app also applies this migration automatically if `relationship_state.energy` is missing (same `DB_URL` as the server).

If your DB predates **bot initiative** (`bots.initiative`: low / medium / high):

```powershell
psql $env:DB_URL -f src/companion/migrations/011_bot_initiative.sql
```

On startup, the app also adds `bots.initiative` automatically if the column is missing.

## Run tests

Tests will automatically:
- use `companion_test`
- reset schema once per test session (via `tests/conftest.py`)

Run:
```powershell
pytest -q
```

## Run CLI demo

This is a small demo CLI that calls the service layer.

```powershell
$env:PYTHONPATH = "$PWD\src"
python .\chat_cli.py
```
