-- Legacy: if only 012 ran, 013 migrates to user-chosen four-style enum.
ALTER TABLE bots
ADD COLUMN IF NOT EXISTS personality TEXT NOT NULL DEFAULT 'gentle'
  CHECK (personality IN ('tsundere', 'playful', 'cool', 'gentle'));
