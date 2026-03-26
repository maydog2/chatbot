ALTER TABLE relationship_state
ADD COLUMN IF NOT EXISTS energy DOUBLE PRECISION NOT NULL DEFAULT 56 CHECK (energy BETWEEN 0 AND 100),
ADD COLUMN IF NOT EXISTS irritation DOUBLE PRECISION NOT NULL DEFAULT 16 CHECK (irritation BETWEEN 0 AND 100),
ADD COLUMN IF NOT EXISTS outwardness DOUBLE PRECISION NOT NULL DEFAULT 46 CHECK (outwardness BETWEEN 0 AND 100),
ADD COLUMN IF NOT EXISTS baseline_energy DOUBLE PRECISION NOT NULL DEFAULT 56 CHECK (baseline_energy BETWEEN 0 AND 100),
ADD COLUMN IF NOT EXISTS baseline_irritation DOUBLE PRECISION NOT NULL DEFAULT 16 CHECK (baseline_irritation BETWEEN 0 AND 100),
ADD COLUMN IF NOT EXISTS baseline_outwardness DOUBLE PRECISION NOT NULL DEFAULT 46 CHECK (baseline_outwardness BETWEEN 0 AND 100),
ADD COLUMN IF NOT EXISTS last_mood_update_at TIMESTAMPTZ NOT NULL DEFAULT now(),
ADD COLUMN IF NOT EXISTS last_mood_changed_at TIMESTAMPTZ NOT NULL DEFAULT now();

UPDATE relationship_state
SET
  energy = CASE
    WHEN mood = 'Tired' THEN LEAST(energy, 24)
    WHEN mood = 'Happy' THEN GREATEST(energy, 72)
    WHEN mood = 'Playful' THEN GREATEST(energy, 78)
    ELSE energy
  END,
  irritation = CASE
    WHEN mood = 'Irritated' THEN GREATEST(irritation, 72)
    ELSE irritation
  END,
  outwardness = CASE
    WHEN mood = 'Quiet' THEN LEAST(outwardness, 20)
    WHEN mood = 'Playful' THEN GREATEST(outwardness, 75)
    WHEN mood = 'Happy' THEN GREATEST(outwardness, 62)
    ELSE outwardness
  END,
  baseline_energy = COALESCE(baseline_energy, 56),
  baseline_irritation = COALESCE(baseline_irritation, 16),
  baseline_outwardness = COALESCE(baseline_outwardness, 46),
  last_mood_update_at = COALESCE(last_mood_update_at, now()),
  last_mood_changed_at = COALESCE(last_mood_changed_at, now());
