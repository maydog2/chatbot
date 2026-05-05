DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'bots'::regclass
      AND conname = 'bots_session_id_unique'
  ) THEN
    ALTER TABLE bots
      ADD CONSTRAINT bots_session_id_unique UNIQUE (session_id);
  END IF;
END $$;
