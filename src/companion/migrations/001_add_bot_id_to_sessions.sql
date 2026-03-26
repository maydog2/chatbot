-- One bot = one session; bot holds session_id (no bot_id on sessions).
-- Run on existing DBs: create bots table; remove bot_id from sessions if it existed.

CREATE TABLE IF NOT EXISTS bots (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
  name            TEXT NOT NULL,
  system_prompt   TEXT NOT NULL,
  avatar_data_url TEXT,
  direction       TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_bots_user_id ON bots(user_id);

ALTER TABLE sessions DROP COLUMN IF EXISTS bot_id;
DROP INDEX IF EXISTS idx_sessions_user_bot;
