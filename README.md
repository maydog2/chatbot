# ChatBot

A full-stack AI companion chat platform with persistent sessions, customizable bots, and relationship-aware conversation state.

**Live Demo:** [Frontend (Vercel)](https://chatbot-delta-livid-14.vercel.app) · [API docs (Render)](https://chatbot-vpea.onrender.com/docs)  
**GitHub:** [maydog2/chatbot](https://github.com/maydog2/chatbot)  

## Tech Stack

### Languages & runtimes
- **Python 3**
- **TypeScript**
- **Node.js**

### Backend
- **FastAPI** — HTTP API
- **Uvicorn** — ASGI server
- **Pydantic** — request/response models
- **psycopg** + **psycopg-pool** — PostgreSQL driver & connection pool

### Frontend
- **Next.js 14** (App Router)
- **React 18**

### Data
- **PostgreSQL**

### Auth & security
- **Bearer token** session model (signed tokens)
- **bcrypt** — password hashing

### AI
- **OpenAI Python SDK** — chat completions via **OpenAI-compatible** endpoints (Respan Gateway, OpenAI, Groq, etc.)

### Configuration
- **python-dotenv** — load repo-root `.env` locally (not required on hosts that inject env vars)

### Testing
- **pytest** — API & service tests

### Hosting
- **Render** — backend API
- **Vercel** — frontend
- **Neon** — PostgreSQL

## Features

- **Authentication** — Register, log in, and use bearer-token-based sessions with optional remember-me support.
- **Companion management** — Create and manage multiple bots per account, each with its own persona, interests, initiative level, avatar, and persistent conversation history.
- **Persistent conversations** — Resume chats across visits with durable session and message storage.
- **Relationship-aware responses** — Replies incorporate persistent companion state, including trust, resonance, affection, openness, mood, interests, and initiative.
- **Gomoku minigame** — In-game side chat uses the same bot session for persistence; relationship metrics can also refresh immediately during the game.
- **LLM provider support** — Integrate with OpenAI-compatible chat providers using configurable model and endpoint settings.

## Respan Integration

The backend calls LLMs through **Respan Gateway** using OpenAI-compatible chat completions. The main chat flow is:

```text
User sends message
    ↓
FastAPI builds companion prompt
    ↓
Attach relationship-state metadata
    ↓
Call LLM through Respan Gateway
    ↓
Run local role-consistency evaluator
    ↓
Return response
```

Key implementation paths:

- `src/companion/api/routes/chat.py` — FastAPI chat routes
- `src/companion/service/chat.py` — prompt assembly and chat-turn orchestration
- `src/companion/infra/llm.py` — Respan/OpenAI-compatible gateway client
- `src/companion/service/persona_guard.py` — local role-consistency checks and rewrite instructions

For environment variables, deployment setup, and gateway verification, see `docs/DEPLOYMENT.md`.

## Project Structure

```
ChatBot/
├── src/companion/          # Backend package (FastAPI app, domain, service, infra, SQL)
│   ├── api.py              # HTTP routes
│   ├── domain/             # Domain rules (initiative, interests, relationship triggers, …)
│   ├── infra/              # DB pool, LLM client, init_db / list_tables helpers
│   ├── service/            # Application services
│   ├── migrations/         # Incremental SQL migrations
│   ├── schema.sql          # Base schema
│   └── reset.sql           # Full reset (tests / dev)
├── frontend/               # Next.js 14 app (App Router)
│   ├── app/                # Pages & layout
│   ├── lib/                # API client & UI helpers
│   └── public/             # Static assets
├── tests/                  # pytest (API, service, domain)
├── scripts/                # Small CLI utilities (e.g. admin/diagnostics)
├── requirements.txt        # Python dependencies
└── README.md
```

## Quick Start

The commands in this section are **Windows PowerShell** (path separators, `Activate.ps1`, `$env:…`, `copy`). On **macOS / Linux**, use the same ideas: `source .venv/bin/activate`, `export PYTHONPATH="$PWD/src"`, `cp` instead of `copy`, and Unix-style paths.

### Prerequisites

- **Python 3.11+** (recommended) and **Node.js 18+**
- A running **PostgreSQL** instance and a connection string (`DB_URL`)
- A **Respan Gateway** API key (`RESPAN_API_KEY`) or another **OpenAI-compatible** API key if you want LLM replies

### 1) Backend API

From the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set at least **`DB_URL`**, **`AUTH_TOKEN_SECRET`**, and an LLM provider key such as **`RESPAN_API_KEY`**. See `docs/DEPLOYMENT.md` for the full Respan Gateway configuration.

Initialize the schema once (empty database):

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m companion.infra.init_db
```

Run the API:

```powershell
$env:PYTHONPATH = "$PWD\src"
uvicorn companion.api:app --reload --host 0.0.0.0 --port 8000
```

Open **http://127.0.0.1:8000/docs** for interactive API docs.

### 2) Frontend (Next.js)

In a second terminal:

```powershell
cd frontend
copy .env.local.example .env.local
# Set NEXT_PUBLIC_API_URL to your API base, e.g. http://127.0.0.1:8000
npm install
npm run dev
```

Open **http://localhost:3000**.

### 3) Tests (optional)

```powershell
$env:PYTHONPATH = "$PWD\src"
pytest -q
```

(`tests/conftest.py` expects a local `companion_test` database by default—configure `TEST_DB_URL` if needed.)

## Known Limitations

- Relationship-state updates are heuristic and still being tuned.
- No long-term semantic memory yet; the system persists chat history and relationship/session signals, but does not currently use retrieval-augmented memory.
- Guardrails and evaluation coverage for adversarial or edge-case prompts are still limited; response safety and consistency currently rely primarily on prompt design and application-level constraints..
- Single-region, cloud-dependent deployment; cold starts and network latency across Render, Vercel, and the database provider may affect responsiveness.