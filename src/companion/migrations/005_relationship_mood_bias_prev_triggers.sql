-- Short-term mood bias (decaying offset from stats-based mood) + last turn's triggers (repeat decay).
ALTER TABLE relationship_state
  ADD COLUMN IF NOT EXISTS mood_recent_bias INT NOT NULL DEFAULT 0
    CHECK (mood_recent_bias BETWEEN -5 AND 5),
  ADD COLUMN IF NOT EXISTS prev_turn_triggers JSONB NOT NULL DEFAULT '[]'::jsonb;
