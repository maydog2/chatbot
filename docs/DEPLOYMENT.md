# Deployment Guide

## Quick deployment checklist

First time wiring everything up? Do it in this order, then use the sections below for commands, env var names, and troubleshooting.

1. **Create a Neon database** — copy the pooled `DB_URL`.
2. **Deploy the backend on Render** — Web Service from this repo, root = repo root, start command with `PYTHONPATH=src` + Uvicorn (see [Backend Deployment](#backend-deployment)).
3. **Set backend environment variables** on Render — at minimum `DB_URL`, `AUTH_TOKEN_SECRET`, and LLM-related keys; run **`init_db` once** against Neon before relying on the UI (see [Database Configuration](#database-configuration)).
4. **Deploy the frontend on Vercel** — same repo, **Root Directory = `frontend`**, turn **off** “include files outside root” (see [Frontend Deployment](#frontend-deployment)).
5. **Set `NEXT_PUBLIC_API_URL` on Vercel** to your public Render API URL (HTTPS, no trailing slash); **redeploy** the frontend.
6. **Update `CORS_ALLOW_ORIGINS` on Render** to include your real Vercel origin(s) (comma-separated, no spaces); **redeploy** the backend.
7. **Run post-deployment verification** — `/docs` on the API, register/login from the Vercel URL (see [Post-Deployment Verification](#post-deployment-verification)).

---

## Overview

This repo is a **monorepo**: the **Next.js** UI lives under `frontend/`, and the **FastAPI** API lives under `src/companion/` at the repository root.

Typical production layout:

| Layer | Platform | Role |
|-------|----------|------|
| Frontend | **Vercel** | Serves the web app; calls the API from the browser |
| Backend | **Render** | Runs **Uvicorn** + FastAPI |
| Database | **Neon** | Managed **PostgreSQL** |

The browser always talks to the API over **HTTPS** using the public API base URL (configured as `NEXT_PUBLIC_API_URL` on Vercel).

---

## Services

This section is a **high-level map only**—what each piece is for. **Concrete settings, commands, and env vars** are in [Backend Deployment](#backend-deployment), [Frontend Deployment](#frontend-deployment), and [Database Configuration](#database-configuration) below.

### Frontend (Vercel)

Serves the **Next.js** app from the `frontend/` directory. Users open it in the browser; the app calls the API using **`NEXT_PUBLIC_API_URL`** (your Render service, HTTPS). Preview vs production URLs differ—**CORS** on the backend must allow whichever origin you actually use.

### Backend (Render)

Runs **FastAPI** behind **Uvicorn** from the **repository root** (`requirements.txt`, `src/companion/`). Exposes REST routes and **`/docs`** on the public host Render assigns.

### Database (Neon)

Managed **PostgreSQL**. The API uses **`DB_URL`**; you apply the schema once with **`init_db`** (see Database Configuration), not by hand-editing Neon’s console for a greenfield deploy.

---

## Required Environment Variables

### Frontend (Vercel)

| Variable | Required | Description |
|----------|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Yes | Public base URL of the Render API, **no trailing slash**, e.g. `https://your-api.onrender.com` |

After changing this variable, **redeploy** the frontend so the value is baked into the client bundle.

### Backend (Render)

| Variable | Required | Description |
|----------|----------|-------------|
| `DB_URL` | Yes | Neon PostgreSQL connection string |
| `AUTH_TOKEN_SECRET` | Yes | Long random secret used to sign auth tokens |
| `OPENAI_API_KEY` | Yes* | API key for chat (OpenAI, Groq `gsk_...`, etc.) |
| `OPENAI_BASE_URL` | Optional | Set to Groq when using Groq: `https://api.groq.com/openai/v1` |
| `OPENAI_MODEL` | Optional | Model id (provider-specific) |
| `CORS_ALLOW_ORIGINS` | Yes (prod) | Comma-separated browser origins allowed to call the API (see below) |
| `CHATBOT_LOG_INITIATIVE` | Optional | `1` / `true` to log initiative diagnostics |
| `CHATBOT_LOG_GOMOKU_SUMMARY` | Optional | `1` / `true` to log client `position_summary` JSON during Gomoku side-chat |
| `CHATBOT_INITIATIVE_TONE_LLM` | Optional | Enable LLM-based tone hints for initiative |
| `CHATBOT_TONE_MODEL` | Optional | Model for tone classifier |

\*Required if you use endpoints that call the LLM; otherwise the API may start but chat features return errors.

Render does **not** use a repo-root `.env` file for secrets; set everything in the Render **Environment** UI.

---

## Backend Deployment

1. In Render, **New → Web Service** and select this GitHub repo.
2. Connect the **branch** you ship from (usually `main`) and leave **auto-deploy** enabled if you want pushes to redeploy the service.
3. **Runtime**: Python 3.x (match your local version if possible).
4. **Root Directory**: **empty** (repo root—`requirements.txt` and `src/companion/` live here).
5. **Build Command**: `pip install -r requirements.txt`
6. **Start Command**:

   ```bash
   PYTHONPATH=src uvicorn companion.api:app --host 0.0.0.0 --port $PORT
   ```

7. Add all **backend** environment variables (see [Required Environment Variables](#required-environment-variables)).
8. Deploy and wait until the service is **Live**.
9. **One-time**: apply the database schema to the empty Neon database (see [Database Configuration](#database-configuration)).

---

## Frontend Deployment

1. In Vercel, **Add New Project** and import the same GitHub repo.
2. **Root Directory**: `frontend` (so `npm install` / `next build` run against `frontend/package.json`).
3. **Framework**: **Next.js** (auto-detected). This repo includes `frontend/vercel.json` to pin install/build commands if detection is flaky.
4. **Root Directory (critical for monorepos):** open **Project → Settings → General → Root Directory** and turn **off** **“Include files outside the root directory in the Build Step”**, then **Save**.  
   If this stays **on**, Vercel may incorporate files outside `frontend/` during the build, **skip a proper Next.js output**, and you can get **`404: NOT_FOUND`** or a Deployment Summary that says **“No framework detected”** and lists only a stray static asset. After toggling, **Redeploy** (prefer **without build cache**).
5. Under **Environment Variables**, set **`NEXT_PUBLIC_API_URL`** to your Render API base URL (**HTTPS**, **no trailing slash**).
6. **Deploy**. Changing `NEXT_PUBLIC_API_URL` later requires a **new deployment** so the client bundle picks it up.

**Domains:** use **Settings → Domains** for a stable production hostname. Preview URLs change every deploy—either add those origins to **`CORS_ALLOW_ORIGINS`** on Render or test only on the production domain to avoid repeated CORS edits.

---

## Database Configuration

**Neon setup (conceptual):** create a project/database in [Neon](https://neon.tech). Prefer the **pooled** connection string for server-side APIs. Keep **`sslmode=require`**. If you hit TLS / channel-binding issues on some clients, try Neon’s connection string variant **without** `channel_binding=require`.

1. Copy **`DB_URL`** from Neon into Render’s environment (same value the API will use).
2. From your machine (with `PYTHONPATH=src` and `DB_URL` set), run **once**:

   ```bash
   python -m companion.infra.init_db
   ```

   Or pass `--db` explicitly if you do not use `.env` locally.

3. Do **not** run `init_db --reset` against production unless you intend to wipe data.

Migrations for older databases are under `src/companion/migrations/`; new Neon databases created from current `schema.sql` via `init_db` usually do not need manual migration steps.

---

## CORS and Domain Configuration

The API uses FastAPI’s `CORSMiddleware`. Allowed origins are:

- Defaults: `http://localhost:3000`, `http://127.0.0.1:3000`
- Plus any origins listed in **`CORS_ALLOW_ORIGINS`** (comma-separated, **no spaces**, no trailing slashes):

  Example:

  ```text
  http://localhost:3000,http://127.0.0.1:3000,https://your-app.vercel.app
  ```

After changing `CORS_ALLOW_ORIGINS`, **redeploy** or restart the Render service.

If the frontend shows **Failed to fetch** but the API works in `/docs`, CORS is the first thing to check.

---

## Post-Deployment Verification

1. **API**: Open `https://<your-render-host>/docs` — Swagger should load.
2. **Health**: From the API docs, try `POST /users/register` with a test user (or use the frontend Register flow).
3. **Frontend**: Open your Vercel URL, register/login, and send a message.
4. **Browser DevTools → Network**: Confirm requests go to `NEXT_PUBLIC_API_URL` and return `200`/`401` as expected (not blocked as CORS errors).

---

## Troubleshooting

| Symptom | Likely cause | What to do |
|---------|----------------|------------|
| Vercel shows **`404: NOT_FOUND`** or Deployment Summary says **“No framework detected”** and only lists e.g. one `public/` asset | Monorepo build pulled files outside `frontend/` | Turn **off** “Include files outside the root directory in the Build Step” under Root Directory settings; clear custom empty **Build/Output** overrides; **Redeploy without cache** |
| `Failed to fetch` from Vercel UI | CORS or wrong API URL | Set `CORS_ALLOW_ORIGINS` to include your exact Vercel origin; fix `NEXT_PUBLIC_API_URL`; redeploy both sides |
| API `/docs` works, UI login fails silently | CORS | Same as above |
| `401` on login | Wrong password or user only exists in another DB | Register on production or align `DB_URL` with the DB where the user was created |
| Slow first request | Render free-tier cold start | Normal; retry after a few seconds |
| DB connection errors | Wrong `DB_URL`, SSL params, or Neon paused | Verify string in Neon dashboard; ensure `sslmode=require` |
| LLM errors | Missing `OPENAI_API_KEY` or wrong `OPENAI_BASE_URL` for Groq | Set keys in Render; for Groq set base URL and model |

---

## Operational Notes

- **Secrets**: Rotate `AUTH_TOKEN_SECRET` and API keys if they are ever exposed; update Render (and Vercel for frontend-only secrets).
- **GitHub → Render/Vercel**: Pushes to the connected branch usually trigger automatic redeploys; confirm auto-deploy is enabled per service.
- **Stable URLs**: Prefer documenting and allowlisting the **Vercel production domain** instead of ephemeral preview hostnames.
- **Costs / sleep**: Free tiers may spin down; plan for cold starts or upgrade instances for consistent latency.
