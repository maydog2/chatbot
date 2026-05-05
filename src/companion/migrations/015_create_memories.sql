CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS memories (
  id                BIGSERIAL PRIMARY KEY,
  user_id           BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id        BIGINT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  source_message_id BIGINT REFERENCES messages(id) ON DELETE SET NULL,
  content           TEXT NOT NULL CHECK (length(btrim(content)) > 0),
  memory_type       TEXT NOT NULL CHECK (memory_type IN ('preference', 'goal', 'background', 'instruction')),
  importance        INT NOT NULL DEFAULT 50 CHECK (importance BETWEEN 0 AND 100),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  is_active         BOOLEAN NOT NULL DEFAULT true,
  embedding         vector
);

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'memories'
      AND column_name = 'embedding'
      AND data_type = 'ARRAY'
  ) THEN
    EXECUTE $alter$
      ALTER TABLE memories
        ALTER COLUMN embedding TYPE vector
        USING CASE
          WHEN embedding IS NULL THEN NULL
          ELSE ('[' || array_to_string(embedding, ',') || ']')::vector
        END
    $alter$;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_memories_user_active
  ON memories(user_id, is_active, importance DESC, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_session_created
  ON memories(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memories_source_message_id
  ON memories(source_message_id);

CREATE OR REPLACE FUNCTION companion_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_memories_updated_at ON memories;

CREATE TRIGGER trg_memories_updated_at
BEFORE UPDATE ON memories
FOR EACH ROW
EXECUTE PROCEDURE companion_set_updated_at();
