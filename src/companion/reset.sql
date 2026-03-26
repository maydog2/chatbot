SET TIME ZONE 'UTC';

-- Drop tables (also drops dependent indexes/triggers via CASCADE)
DROP TABLE IF EXISTS messages CASCADE;
DROP TABLE IF EXISTS bots CASCADE;
DROP TABLE IF EXISTS sessions CASCADE;
DROP TABLE IF EXISTS relationship_state CASCADE;
DROP TABLE IF EXISTS users CASCADE;

-- Optional: drop function too (reset should be thorough)
DROP FUNCTION IF EXISTS companion_set_updated_at() CASCADE;

CREATE TABLE users (
  id            BIGSERIAL PRIMARY KEY,
  username      TEXT NOT NULL UNIQUE CHECK (length(btrim(username)) > 0),
  display_name  TEXT NOT NULL CHECK (length(btrim(display_name)) > 0),
  avatar_data_url TEXT,
  password_hash TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE sessions (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at      TIMESTAMPTZ
);

CREATE INDEX idx_sessions_user_started
  ON sessions(user_id, started_at DESC);

CREATE TABLE bots (
  id              BIGSERIAL PRIMARY KEY,
  user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id      BIGINT NOT NULL REFERENCES sessions(id) ON DELETE RESTRICT,
  name            TEXT NOT NULL,
  system_prompt   TEXT NOT NULL,
  avatar_data_url TEXT,
  direction         TEXT,
  form_of_address   TEXT,
  primary_interest  TEXT,
  secondary_interests JSONB NOT NULL DEFAULT '[]'::jsonb,
  initiative      TEXT NOT NULL DEFAULT 'medium' CHECK (initiative IN ('low', 'medium', 'high')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_bots_user_id ON bots(user_id);

CREATE TABLE messages (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id    BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role          TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content       TEXT NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_messages_user_created
  ON messages(user_id, created_at DESC);

CREATE INDEX idx_messages_session_created
  ON messages(session_id, created_at ASC);

CREATE TABLE relationship_state (
  bot_id        BIGINT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  trust         INT NOT NULL DEFAULT 40 CHECK (trust BETWEEN 0 AND 100),
  resonance     INT NOT NULL DEFAULT 30 CHECK (resonance BETWEEN 0 AND 100),
  affection     INT NOT NULL DEFAULT 40 CHECK (affection BETWEEN 0 AND 100),
  openness      INT NOT NULL DEFAULT 30 CHECK (openness BETWEEN 0 AND 100),
  mood          TEXT NOT NULL DEFAULT 'Calm' CHECK (mood IN ('Calm', 'Quiet', 'Happy', 'Irritated', 'Playful', 'Tired')),
  energy        DOUBLE PRECISION NOT NULL DEFAULT 56 CHECK (energy BETWEEN 0 AND 100),
  irritation    DOUBLE PRECISION NOT NULL DEFAULT 16 CHECK (irritation BETWEEN 0 AND 100),
  outwardness   DOUBLE PRECISION NOT NULL DEFAULT 46 CHECK (outwardness BETWEEN 0 AND 100),
  baseline_energy      DOUBLE PRECISION NOT NULL DEFAULT 56 CHECK (baseline_energy BETWEEN 0 AND 100),
  baseline_irritation  DOUBLE PRECISION NOT NULL DEFAULT 16 CHECK (baseline_irritation BETWEEN 0 AND 100),
  baseline_outwardness DOUBLE PRECISION NOT NULL DEFAULT 46 CHECK (baseline_outwardness BETWEEN 0 AND 100),
  last_mood_update_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_mood_changed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  mood_recent_bias INT NOT NULL DEFAULT 0 CHECK (mood_recent_bias BETWEEN -5 AND 5),
  prev_turn_triggers JSONB NOT NULL DEFAULT '[]'::jsonb,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_relationship_state_user_id ON relationship_state(user_id);

CREATE OR REPLACE FUNCTION companion_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_relationship_state_updated_at
BEFORE UPDATE ON relationship_state
FOR EACH ROW
EXECUTE PROCEDURE companion_set_updated_at();


CREATE TABLE IF NOT EXISTS auth_tokens(
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    TEXT NOT NULL UNIQUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at    TIMESTAMPTZ NOT NULL,
  revoked_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_auth_tokens_user_id ON auth_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_auth_tokens_valid ON auth_tokens(token_hash, expires_at, revoked_at);