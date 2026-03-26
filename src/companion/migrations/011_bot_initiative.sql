ALTER TABLE bots
ADD COLUMN IF NOT EXISTS initiative TEXT NOT NULL DEFAULT 'medium'
  CHECK (initiative IN ('low', 'medium', 'high'));
