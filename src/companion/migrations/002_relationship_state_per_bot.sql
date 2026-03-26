-- Move relationship_state from user_id-keyed to bot_id-keyed.
-- Creates a new per-bot relationship_state table, copies values for each bot, then swaps tables.
-- Safe to run multiple times (uses IF EXISTS/IF NOT EXISTS where possible).

BEGIN;

-- 1) Create new table if not exists (per-bot).
CREATE TABLE IF NOT EXISTS relationship_state_new (
  bot_id        BIGINT PRIMARY KEY REFERENCES bots(id) ON DELETE CASCADE,
  user_id       BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  trust         INT NOT NULL DEFAULT 40 CHECK (trust BETWEEN 0 AND 100),
  resonance     INT NOT NULL DEFAULT 30 CHECK (resonance BETWEEN 0 AND 100),
  affection     INT NOT NULL DEFAULT 40 CHECK (affection BETWEEN 0 AND 100),
  openness      INT NOT NULL DEFAULT 30 CHECK (openness BETWEEN 0 AND 100),
  mood          TEXT NOT NULL DEFAULT 'Calm' CHECK (mood IN ('Calm', 'Quiet', 'Happy', 'Irritated', 'Playful', 'Tired')),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_relationship_state_new_user_id ON relationship_state_new(user_id);

-- 2) Copy data:
-- If old relationship_state is still user_id-keyed, copy per user to each bot.
DO $$
DECLARE
  has_affection boolean;
  has_openness boolean;
  has_mood boolean;
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'relationship_state' AND column_name = 'affection'
  ) INTO has_affection;
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'relationship_state' AND column_name = 'openness'
  ) INTO has_openness;
  SELECT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'relationship_state' AND column_name = 'mood'
  ) INTO has_mood;

  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'relationship_state'
      AND column_name = 'user_id'
  )
  AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'relationship_state'
      AND column_name = 'bot_id'
  )
  THEN
    -- Old table is per-user. Copy per user to each bot.
    EXECUTE
      'INSERT INTO relationship_state_new (bot_id, user_id, trust, resonance, affection, openness, mood, updated_at)
       SELECT
         b.id AS bot_id,
         b.user_id,
         rs.trust,
         rs.resonance,
         ' ||
         CASE
           WHEN has_affection THEN 'COALESCE(rs.affection, rs.trust)'
           ELSE 'rs.trust'
         END ||
         ' AS affection,
         ' ||
         CASE
           WHEN has_openness THEN 'COALESCE(rs.openness, rs.resonance)'
           ELSE 'rs.resonance'
         END ||
         ' AS openness,
         ' ||
         CASE
           WHEN has_mood THEN 'COALESCE(rs.mood, ''Calm'')'
           ELSE '''Calm'''
         END ||
         ' AS mood,
         COALESCE(rs.updated_at, now()) AS updated_at
       FROM bots b
       LEFT JOIN relationship_state rs ON rs.user_id = b.user_id
       ON CONFLICT (bot_id) DO NOTHING';
  ELSE
    -- If relationship_state already has bot_id, just copy rows into new table (idempotent).
    INSERT INTO relationship_state_new (bot_id, user_id, trust, resonance, affection, openness, mood, updated_at)
    SELECT bot_id, user_id, trust, resonance, affection, openness, mood, updated_at
    FROM relationship_state
    ON CONFLICT (bot_id) DO NOTHING;
  END IF;
END $$;

-- 3) Swap tables.
-- Drop trigger tied to old relationship_state (if any) to avoid dependency issues.
DROP TRIGGER IF EXISTS trg_relationship_state_updated_at ON relationship_state;

DROP TABLE IF EXISTS relationship_state_old;
ALTER TABLE IF EXISTS relationship_state RENAME TO relationship_state_old;
ALTER TABLE relationship_state_new RENAME TO relationship_state;

-- 4) Recreate updated_at trigger on new table.
CREATE OR REPLACE FUNCTION companion_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_relationship_state_updated_at ON relationship_state;
CREATE TRIGGER trg_relationship_state_updated_at
BEFORE UPDATE ON relationship_state
FOR EACH ROW
EXECUTE PROCEDURE companion_set_updated_at();

COMMIT;

