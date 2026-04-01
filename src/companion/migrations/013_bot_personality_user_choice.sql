-- User-selected game reply style only (no auto classification). Replaces five-value enum.
ALTER TABLE bots DROP CONSTRAINT IF EXISTS bots_personality_check;

UPDATE bots SET personality = CASE personality
  WHEN 'lively' THEN 'playful'
  WHEN 'cold' THEN 'cool'
  WHEN 'default' THEN 'gentle'
  ELSE personality
END;

UPDATE bots SET personality = 'gentle'
WHERE personality IS NULL OR personality NOT IN ('tsundere', 'playful', 'cool', 'gentle');

ALTER TABLE bots ADD CONSTRAINT bots_personality_check
  CHECK (personality IN ('tsundere', 'playful', 'cool', 'gentle'));

ALTER TABLE bots ALTER COLUMN personality SET DEFAULT 'gentle';
