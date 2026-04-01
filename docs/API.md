# API Reference

## 1. Overview

This API powers the chatbot application backend. It provides authentication, bot management, persistent conversations, relationship-state tracking, and LLM-backed messaging, with additional support for game-related interaction features.

## 2. Base URL

- **Local:** `http://127.0.0.1:8000`.
- **Production:** set **`NEXT_PUBLIC_API_URL`** on the frontend (HTTPS, no trailing slash), e.g. `https://your-api.onrender.com`.

## 3. Authentication

Most endpoints require a bearer token in the `Authorization` header:

```http
Authorization: Bearer <access_token>
```

Token format, validation, TTL, and logout: **[Appendix A — Tokens and logout](#appendix-a--tokens-and-logout)**.

## 4. Error handling

| Code | Typical meaning |
|------|-----------------|
| **200** | Success |
| **400** | Client or domain error |
| **401** | Authentication required or failed |
| **404** | Resource not found |
| **422** | Request validation failed |
| **503** | Dependency unavailable (e.g. upstream / config) |
| **500** | Server error |

Per-route status patterns, response bodies, and **401** `detail` strings: **[Appendix B — Current HTTP behavior and edge cases](#appendix-b--current-http-behavior-and-edge-cases)**.

---

## 5. API reference

In this section, **Authentication: Required** means a valid bearer token unless the route says otherwise.

### Auth

#### POST /users/register

Creates a user.

**Authentication:** Not required.

**Request body**

```json
{
  "display_name": "Alice",
  "username": "alice",
  "password": "secret"
}
```

**Response**

```json
{ "user_id": 1 }
```

**Notes**

- **400** if username taken or validation fails.

#### POST /users/login

Returns an access token for protected routes.

**Authentication:** Not required.

**Request body**

```json
{
  "username": "alice",
  "password": "secret",
  "remember_me": true
}
```

(`remember_me` optional, default `true`.)

**Response**

```json
{
  "access_token": "<opaque-token>",
  "token_type": "bearer",
  "expires_at": "2026-03-27T12:00:00+00:00"
}
```

**Notes**

- **401** if credentials invalid. TTL: [Appendix A](#appendix-a--tokens-and-logout).

#### POST /users/logout

Revokes the presented bearer token if it matches a row; always **200**.

**Authentication:** Not required (optional `Authorization: Bearer …`).

**Request body:** none.

**Response**

```json
{ "revoked": true }
```

or `{ "revoked": false }`.

**Notes**

- Semantics of **`revoked`**: [Appendix A](#appendix-a--tokens-and-logout).

---

### Users

#### GET /users/me

Current user profile.

**Authentication:** Required.

**Response**

```json
{
  "display_name": "Alice",
  "avatar_data_url": null
}
```

**Notes**

- `avatar_data_url` may be a data URL string or `null`.

#### PATCH /users/me

Updates only fields present in the JSON body.

**Authentication:** Required.

**Request body** (all optional)

```json
{
  "display_name": "Allie",
  "avatar_data_url": null
}
```

**Response:** same shape as GET /users/me.

**Notes**

- **400** if an update violates validation.

---

### Bots

#### GET /bots

Lists the current user’s bots.

**Authentication:** Required.

**Response**

```json
{
  "bots": [
    {
      "id": 1,
      "user_id": 1,
      "session_id": 10,
      "name": "My Bot",
      "system_prompt": "...",
      "avatar_data_url": null,
      "direction": "a helpful companion",
      "form_of_address": null,
      "primary_interest": "anime",
      "secondary_interests": ["music"],
      "initiative": "medium",
      "personality": "gentle",
      "created_at": "2026-03-27T10:00:00"
    }
  ]
}
```

**Notes**

- Field semantics: [Appendix C](#appendix-c--prompts-llm-and-send-bot-message). Fetching a single bot by id: [Appendix B](#appendix-b--current-http-behavior-and-edge-cases).
- **`personality`:** in-app game/side-chat reply style: `playful` | `cool` | `gentle` | `tsundere` (default `gentle` on create).

#### POST /bots

Creates a bot, session, initial `system_prompt`, and relationship row.

**Authentication:** Required.

**Request body**

```json
{
  "name": "My Bot",
  "direction": "Warm and curious.",
  "avatar_data_url": null,
  "form_of_address": null,
  "primary_interest": "anime",
  "secondary_interests": ["games"],
  "initiative": "medium",
  "personality": "gentle"
}
```

(`primary_interest` required; `initiative` is `low` | `medium` | `high`; `personality` optional, default `gentle`.)

**Response:** one bot object (same shape as list items).

**Notes**

- **400** on duplicate name/avatar (per user) or invalid interests.

#### PATCH /bots/{bot_id}

Partial update; changing `direction` / interests can rebuild `system_prompt` from current relationship state.

**Authentication:** Required.

**Path parameters:** `bot_id`

**Request body** (all optional)

```json
{
  "name": "Renamed",
  "direction": "More playful.",
  "initiative": "high",
  "personality": "playful"
}
```

**Response:** updated bot object.

**Notes**

- **400** if bot missing for user or validation fails.

#### DELETE /bots/{bot_id}

Deletes the bot and its session (messages cascade).

**Authentication:** Required.

**Path parameters:** `bot_id`

**Response**

```json
{ "deleted": true }
```

**Notes**

- **404** if bot not found for user.

---

### Chat

#### POST /chat/send-bot-message

Main chat: **saves** the user message, **calls the LLM**, **saves** the assistant reply, updates relationship/mood logic server-side; returns `assistant_reply` and metrics.

**Authentication:** Required.

**Request body**

```json
{
  "bot_id": 1,
  "content": "Hello!",
  "system_prompt": "",
  "trust_delta": 0,
  "resonance_delta": 0,
  "include_initiative_debug": false
}
```

Optional **`ephemeral_game`** (Gomoku side-chat while playing): same top-level fields as above, plus:

```json
{
  "bot_id": 1,
  "content": "Nice move.",
  "system_prompt": "",
  "trust_delta": 0,
  "resonance_delta": 0,
  "include_initiative_debug": false,
  "ephemeral_game": {
    "active_game": {
      "type": "gomoku",
      "difficulty": "serious",
      "current_turn": "user",
      "bot_side": "white"
    },
    "game_messages": [
      { "role": "user", "content": "Earlier line in the minigame thread." },
      { "role": "assistant", "content": "Earlier reply in the minigame thread." }
    ],
    "position_summary": null,
    "relationship_events": []
  }
}
```

- **`ephemeral_game.active_game`:** `type` is always `"gomoku"`; `difficulty` is `relaxed` | `serious`; `current_turn` is `user` | `bot`; `bot_side` is `white` | `black`.
- **`ephemeral_game.game_messages`:** each item **`role`** must be **`user`** or **`assistant`** only (no `system`)—otherwise validation returns **422**.
- **`ephemeral_game.position_summary`:** optional JSON object from the client’s board analysis (shape is client-defined; used to steer the reply and to derive relationship hints server-side when present).
- **`ephemeral_game.relationship_events`:** optional list of server-known event id strings (e.g. `user_win`, `bot_win`); merged with hints derived from `position_summary` when applicable. See **POST /games/gomoku/relationship-events** for the same id vocabulary.

**Response**

```json
{
  "session_id": 10,
  "message_id": 101,
  "assistant_message_id": 102,
  "assistant_reply": "Hi there!",
  "trust": 40,
  "resonance": 30,
  "affection": 40,
  "openness": 30,
  "mood": "Calm",
  "display_name": "Alice"
}
```

**Notes**

- **400** if `bot_id` is not owned by the user.
- **With `ephemeral_game`:** the **current** user message and **assistant** reply are still **written** to the bot’s normal **`messages`** transcript (same `session_id` as without a minigame). The effective LLM transcript is built from **persisted** history; `game_messages` is **not** re-appended to the model input (avoids duplicating lines once they are stored).
- Prompt construction, minigame constraints, and debug-only fields: [Appendix C](#appendix-c--prompts-llm-and-send-bot-message) and [Appendix D](#appendix-d--debug-and-unstable-fields).

#### POST /chat/history/bot

Returns up to `limit` messages for that bot’s session, chronological order.

**Authentication:** Required.

**Request body**

```json
{
  "bot_id": 1,
  "limit": 50
}
```

**Response**

```json
{
  "messages": [
    {
      "id": 101,
      "user_id": 1,
      "session_id": 10,
      "role": "user",
      "content": "Hello!",
      "created_at": "2026-03-27T10:00:05"
    }
  ]
}
```

**Notes**

- Does not call the LLM. History/`bot_id` behavior: [Appendix B](#appendix-b--current-http-behavior-and-edge-cases).

#### POST /chat/build-prompt

Returns a **preview** `system_prompt` string from `direction` plus the user’s **first** bot’s relationship/profile context (no LLM).

**Authentication:** Required.

**Request body**

```json
{ "direction": "Draft persona text." }
```

**Response**

```json
{ "system_prompt": "…" }
```

**Notes**

- **400** if user has no bots.

#### POST /chat/reply

One LLM completion from `messages` + `system_prompt`; **no DB read/write**.

**Authentication:** Required.

**Request body**

```json
{
  "messages": [{ "role": "user", "content": "Hi" }],
  "system_prompt": "You are helpful."
}
```

**Response**

```json
{ "assistant_reply": "Hello!" }
```

**Notes**

- For persisted bot chat with relationship updates, use **POST /chat/send-bot-message**.

#### POST /chat/end

Ends a **user-level** “current session” (legacy helper); not the same as per-bot `session_id`.

**Authentication:** Required.

**Request body:** none.

**Response**

```json
{ "ended": true }
```

---

### Games

#### POST /games/gomoku/relationship-events

Applies **Gomoku-related** relationship updates **without** calling the LLM and **without** creating chat messages. Intended for **immediate** UI refresh (trust, resonance, affection, openness, mood) when the client detects board outcomes or other discrete game events.

**Authentication:** Required.

**Request body**

```json
{
  "bot_id": 1,
  "relationship_events": ["user_win"],
  "position_summary": null
}
```

- **`bot_id`:** required.
- **`relationship_events`:** optional list of server-known id strings (e.g. `user_win`, `bot_win`, `user_restarted_while_losing`, `user_created_strong_threat`, `user_blocked_bot_threat`). Unknown ids are ignored.
- **`position_summary`:** optional. When present, the server may **append** derived events from `events` / `match_result` (e.g. map `user_created_threat` → `user_created_strong_threat`) and deduplicate with `relationship_events`.

**Response**

Same JSON shape as **GET /bots/{bot_id}/relationship**:

```json
{
  "trust": 41,
  "resonance": 31,
  "affection": 40,
  "openness": 30,
  "mood": "Playful",
  "display_name": "Alice"
}
```

**Notes**

- **422** if body validation fails (e.g. wrong types).
- Invalid or missing bot ownership may surface as **400** / **500** depending on the code path—prefer treating unexpected errors like **GET /bots/{bot_id}/relationship** (see [Appendix B](#appendix-b--current-http-behavior-and-edge-cases)).

---

### Relationship

#### GET /bots/{bot_id}/relationship

Read-only snapshot: trust, resonance, affection, openness, mood, plus the human user’s `display_name` (after server time-drift refresh on mood axes).

**Authentication:** Required.

**Path parameters:** `bot_id`

**Response**

```json
{
  "trust": 40,
  "resonance": 30,
  "affection": 40,
  "openness": 30,
  "mood": "Calm",
  "display_name": "Alice"
}
```

**Notes**

- Metrics change via **POST /chat/send-bot-message**, **POST /games/gomoku/relationship-events**, and other server-side logic—not by writing to this route. Status behavior for this path: [Appendix B](#appendix-b--current-http-behavior-and-edge-cases).

---

## 6. Example flows

**First-time chat**

1. POST /users/register  
2. POST /users/login → save `access_token`  
3. POST /bots  
4. POST /chat/send-bot-message  
5. POST /chat/history/bot  
6. GET /bots/{bot_id}/relationship  
7. POST /users/logout (optional)

**Preview only**

1. Login → POST /bots (if needed)  
2. POST /chat/build-prompt  
3. Optional: POST /chat/reply (nothing persisted)

**Gomoku: immediate relationship refresh (no chat)**

1. Login → POST /bots (if needed)  
2. POST /games/gomoku/relationship-events with `bot_id` and optional `relationship_events` / `position_summary`  
3. GET /bots/{bot_id}/relationship (optional; the POST already returns the same shape)

---

## 7. Notes

Relationship rules and effective prompts are **server-controlled** and may change between releases. Reply wording depends on configured model/provider (`OPENAI_*` env). Use this document with **`GET /docs`**; route-specific behavior is summarized in **Appendix B**.

---

## Appendix A — Tokens and logout

- Header must use the prefix **`Bearer `** exactly (capital **B**, one space)—implementation uses `startswith("Bearer ")`; other spellings yield **401** `missing bearer token`.
- Login returns `access_token` (opaque), `token_type` `"bearer"`, `expires_at` (ISO). The server stores an **HMAC-SHA256 hash** of the token (`AUTH_TOKEN_SECRET`), not the plaintext.
- **Resolution** for protected routes: hash match, `revoked_at IS NULL`, `expires_at > now()` (Postgres `now()`).
- **TTL:** default **30 days** if `remember_me` is true, **7 days** if false; **`AUTH_TOKEN_TTL_SECONDS`** overrides when set (`issue_access_token`).
- **401 texts:** `missing bearer token` (bad/missing prefix), `missing token` (empty token), `invalid or expired token` (no valid row).
- **Logout:** `POST /users/logout` never returns **401**. Missing/`Bearer`-malformed header → `{ "revoked": false }`. Unknown token → `revoked: false`. **`revoke_token_by_hash`** does not check `expires_at`, so an expired-but-unrevoked row may still return `revoked: true`.

## Appendix B — Current HTTP behavior and edge cases

How the current handlers attach HTTP statuses and bodies to outcomes—useful for integration and maintenance, not a guarantee of future internals.

**Conventions**

- Successful creates use **200** with a JSON body; **201** is not used in this codebase.
- **403** is not used.
- **`HTTPException`** responses use `{"detail": "<string>"}`.
- **422** validation failures use `{"detail": [ ... ]}` (FastAPI/Pydantic).

**Resource / routing notes**

- There is no **`GET /bots/{bot_id}`**; use **GET /bots** and select by `id`, or keep the `id` from **POST /bots**.
- At the app level, **404** is returned for **DELETE /bots/{bot_id}** when the bot is missing. Other “missing bot” situations may return **400** or **200** with an empty payload—see below.

**Per-route patterns**

- **History:** `POST /chat/history/bot` with unknown `bot_id` for the user → **200**, `"messages": []`.
- **Send message:** wrong `bot_id` → **400**, `detail`: `"bot not found"`.
- **Relationship:** invalid `bot_id` may surface as **500** if the stack raises **`ValueError`** without an **`HTTPException`** wrapper.
- **LLM / config:** missing **`OPENAI_API_KEY`** is often handled inside **`get_reply_for_custom_bot`** with a fallback assistant string → **200** on **send-bot-message** / **reply** in those cases, rather than **503**.
- **503** on LLM routes: some propagated **`RuntimeError`** paths (e.g. invalid API key); see **`except RuntimeError`** on chat (and create-bot) in `companion/api.py`.
- **Games:** **POST /games/gomoku/relationship-events** does not call the LLM; failures are usually **422** (validation) or depend on DB/bot resolution like other authenticated bot-scoped routes.

## Appendix C — Prompts, LLM, and `send-bot-message`

- The **effective** model system prompt for **POST /chat/send-bot-message** is rebuilt server-side from the bot’s **`direction`**, relationship metrics, interests, initiative, addressing, etc. The **`system_prompt`** field in the request body is **not** the sole source for the actual LLM call (compatibility field; implementation ignores it for the real turn prompt).
- **POST /chat/build-prompt** uses the authenticated user’s **first** bot for relationship context when composing text; it does not call the LLM.
- **Provider:** model, base URL, and behavior follow **`OPENAI_API_KEY`**, optional **`OPENAI_BASE_URL`**, **`OPENAI_MODEL`**, etc.; output is non-deterministic across providers and runs.
- **Minigame (`ephemeral_game`):** the server appends **Gomoku** constraints and, when provided, a **board-analysis** block from **`position_summary`** so the model does not contradict the client-held game state. Relationship deltas from **`relationship_events`** / **`position_summary`** may be applied on that turn (in addition to the usual post-reply trigger classifier).

## Appendix D — Debug and unstable fields

- **`include_initiative_debug`: true** on **POST /chat/send-bot-message** may add **`initiative_debug`** to the response. Schema and fields are for troubleshooting only—not a stable public contract.
