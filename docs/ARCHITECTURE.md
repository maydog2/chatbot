# Architecture

## 1. Overview

This project is a **full-stack AI companion chat platform** built around persistent users, bots, sessions, and message history. Authenticated users can create and configure one or more companion bots, converse with them across multiple sessions, and retrieve prior conversation history from durable storage. In addition to storing messages, the system maintains **relationship-aware companion state** so responses can reflect prior interactions and persistent behavioral signals across turns.

The architecture follows a split full-stack model: a **Next.js** frontend for the user-facing web experience, a **FastAPI** backend as the source of truth for business logic and persistence, and **PostgreSQL** for durable data storage. The backend also integrates an **OpenAI-compatible LLM API** to generate assistant responses. In production-style deployments, these responsibilities are typically separated across a frontend host (such as Vercel), a backend service host (such as Render), and a managed PostgreSQL provider (such as Neon). Operational setup is covered in [Deployment](DEPLOYMENT.md).

## 2. Goals and Non-Goals

### Goals

- **Product:** Deliver a usable companion chat product rather than a one-page LLM demo, with accounts, multiple customizable bots per user, persistent sessions, and durable message history.
- **Stateful behavior:** Carry **relationship-style state** and bot-level configuration into prompting so replies stay aligned with each bot’s persona across many turns.
- **Architecture:** Keep a clean split—**Next.js** for interaction, **FastAPI** for orchestration and rules, **PostgreSQL** for durability; integrate an **OpenAI-compatible** provider for generation without locking to one vendor’s API surface.
- **Operations:** Stay deployable on common PaaS patterns (separate UI host, API host, managed DB) with configuration via environment variables and minimal secret sprawl in code.
- **Quality:** Maintain automated tests around HTTP contracts and core services so refactors to prompts or state rules do not silently break users.

### Non-Goals
- **Distributed microservices:** The system is intentionally implemented as a relatively simple split full-stack application rather than a microservice architecture.
- **Multi-region deployment:** Low-latency global replication and cross-region failover are not current goals.
- **Advanced moderation / safety pipeline:** The project does not yet implement a comprehensive safety, red-teaming, or policy-enforcement layer.
- **Long-term semantic memory:** The system persists chat history and companion state, but does not yet include retrieval-augmented memory or vector search.
- **Custom-trained personalization models:** Companion behavior is driven by prompting and heuristic state updates, not fine-tuned or user-specific learned models.
- **High-scale real-time orchestration:** The architecture is designed for a deployable product/demo experience, not for large-scale concurrent chat workloads.

## 3. High-Level Architecture

At runtime, the system is organized into four primary components:

| Component | Responsibility |
| --- | --- |
| Frontend | **Next.js** web client for the user-facing interface, authentication flow, bot/profile management, and chat interaction. |
| Backend API | **FastAPI** service for authentication, session/message APIs, companion-state management, and LLM orchestration. |
| Database | **PostgreSQL** for durable users, bots, sessions, messages, and relationship state (often hosted on Neon in production). |
| LLM provider | **OpenAI-compatible HTTP API** used for assistant generation (for example, OpenAI, Groq, or other compatible providers). |

**Typical production deployment:** Vercel (frontend), Render (backend), and Neon (database). See [Deployment](DEPLOYMENT.md).

Traffic and dependencies in one view:

```
Browser
  │
  ▼
Next.js frontend (Vercel)
  │
  │  HTTPS / JSON API
  ▼
FastAPI backend (Render)
  ├──► PostgreSQL (Neon)
  └──► OpenAI-compatible LLM API
```

The browser never talks to the database or the LLM directly; all persistence and model calls go through the backend.

## 4. Core Data Model

Persistence lives in **PostgreSQL**. The app is organized around a small set of entities—enough to support auth, multi-bot companions, chat transcripts, and evolving “relationship” signals. The list below is **conceptual** (not a column-by-column schema).

| Entity | What it is |
|--------|----------------|
| **User** | Authenticated account (credentials, profile fields used by the UI). |
| **Bot** | A **customizable companion persona** owned by exactly one **User** (name, direction/prompt ingredients, avatar, interests, initiative, etc.). |
| **Session** | Durable **message transcript** container: each **Bot** points at one **`session_id`** row, and that session holds the ordered **Messages** for that bot’s thread. **`POST /chat/end`** ends a **legacy per-user “active” session** (see `sessions.py`), not the normal lifecycle of a bot’s chat transcript. |
| **Message** | A **persisted** turn in that session: **user** or **assistant** role and content, ordered in time. |
| **Relationship state** | **Mutable** per-companion signals (e.g. trust, resonance, affection, openness, **mood**) maintained for a **(User, Bot)** pair; together with bot fields like **initiative**, they influence how prompts and replies are shaped—without listing every field here. |

**Who links to whom:** A **User** has many **Bots**. Each **Bot** drives one active **Session** model in the product (one conversation thread per bot in normal use). A **Session** has many **Messages**. **Relationship state** is associated with the **User + Bot** pair (the emotional/relational “stance” toward that companion), not with a single message row.

**What stays durable:** Accounts, bot definitions, sessions, the message transcript, and relationship/companion state—so reloads, new devices (same account), and later turns can continue coherently. Anything not listed here (e.g. raw LLM provider logs) is generally **not** treated as a first-class persisted entity.

```
User ── owns ──► Bot (many)
                  │
                  ├── Session ◄── chat thread for this bot
                  │      └── Message (many; user / assistant)
                  │
                  └── Relationship state ◄── (User, Bot) metrics + mood
```

## 5. Key Request Flows

These flows match how the **FastAPI** layer and **service** layer behave.

### A. User authentication

1. **Register** — Client calls `POST /users/register` with display name, username, password. The API creates a **User** row (and returns `user_id`).
2. **Login** — Client calls `POST /users/login` with username, password, optional `remember_me`. On success the backend **mints an access token**, persists a hash for revocation, and returns JSON with `access_token`, `token_type` (`bearer`), and `expires_at`.
3. **Authenticated calls** — Protected routes use `Authorization: Bearer <access_token>`. The API resolves the bearer token to the authenticated user for protected routes; invalid or missing tokens yield **401**.
4. **Logout** — `POST /users/logout` with the same bearer token invalidates that token server-side when possible.

Tokens are opaque strings to the client; the UI stores them and attaches them to API requests.

### B. Chat message (send turn)

Typical path: the client sends a chat turn for a specific bot. The backend authenticates the user, resolves the bot/session, persists the user message, builds model context from recent transcript and companion state, calls the LLM provider, stores the assistant reply, applies post-turn state updates, and returns the new reply plus refreshed relationship metrics.

Relationship-state updates may occur at multiple points in the turn pipeline: optional client-provided deltas, server-side updates derived from the latest user turn, and post-reply trigger rules after the assistant response is generated. Game-related interactions may also trigger relationship updates through dedicated endpoints.

1. **Authenticate the user** — Resolve `user_id` from the bearer token.
2. **Resolve the bot and active session** — Load the bot for this user and identify the session backing that bot’s current conversation thread.
3. **Persist the user turn** — Store the new user message and load recent transcript history for context construction.
4. **Refresh companion state** — Apply turn-level relationship/state updates derived from the latest user input, along with any accepted client-provided deltas.
5. **Build effective model input** — Compose the server-side prompt from durable bot/session state, recent transcript, and current relationship signals.
6. **Call the LLM provider** — Send the effective prompt and transcript to the configured OpenAI-compatible API and receive the assistant response.
7. **Post-process and persist the reply** — Apply reply cleanup or initiative-related shaping, then store the assistant message.
8. **Apply post-turn state updates and respond** — Run reply-dependent trigger rules, read fresh relationship values, and return the new assistant reply plus updated companion state needed by the client UI.

The HTTP handler runs inside a per-request database transaction (commit on success, rollback on failure), so a failed step rolls back the entire turn.

### C. History and companion state (read)

1. **History reads** — The backend authenticates the user, verifies bot ownership, resolves the bot/session pair, and returns the most recent transcript from durable storage.
2. **Companion-state reads** — The backend returns current relationship metrics and bot-facing display fields needed by the UI.

Other read paths follow the same pattern: bearer auth, server-side ownership checks where needed, DB read, JSON response.

## 6. Design Decisions

This section captures only system-shaping decisions. A decision is included only when it explains **why** the architecture is this way and what **trade-offs** I accept.

### 1) Split frontend/backend architecture

- **Decision:** Keep a separate Next.js frontend and FastAPI backend with clear API boundaries.
- **Why:** This allows UI iteration to remain independent from backend/domain logic, centralizes authentication and data rules on the server, and avoids exposing database or LLM credentials to the browser.
- **Trade-offs:** It introduces additional operational complexity through two deployable services, and requires stronger coordination around API contracts, CORS, authentication flow, and cross-service observability.

### 2) PostgreSQL as durable storage

- **Decision:** Use PostgreSQL as the source of truth for users, bots, sessions, messages, and relationship state.
- **Why:** The domain is highly relational and consistency-sensitive: messages belong to sessions, sessions belong to bots, and bots belong to users. PostgreSQL fits this model well by providing transactional updates, foreign-key enforcement, and flexible querying over long-lived chat history.
- **Trade-offs:** It requires schema evolution discipline, migrations, and operational ownership around backups, connection management, and performance tuning.

### 3) Heuristic relationship-state model

- **Decision:** Model companion behavior with explicit relationship-state metrics and heuristic update rules rather than a learned personalization model.
- **Why:** Heuristics are transparent, controllable, and easier to adjust quickly as product behavior evolves.
- **Trade-offs:** Behavior can feel less nuanced than learned personalization and may require ongoing rule tuning to avoid edge-case drift.

### 4) OpenAI-compatible provider abstraction

- **Decision:** Use an OpenAI-compatible provider abstraction rather than coupling the backend to a single vendor SDK.
- **Why:** This reduces vendor lock-in and makes it easier to switch providers for cost, latency, or reliability reasons with minimal application-layer change.
- **Trade-offs:** Portability is limited to the shared compatibility surface; provider-specific capabilities may be unavailable or require adapter work.

### 5) Backend-controlled prompt construction

- **Decision:** Build the final LLM prompt on the backend from persisted bot state, relationship state, and chat history, instead of relying on client-provided prompt text alone.
- **Why:** This ensures the model response is based on the real server-side state, while also enforcing ownership checks and backend rules in one place.
- **Trade-offs:** It increases backend complexity and means prompt behavior changes usually require backend updates and deployment.