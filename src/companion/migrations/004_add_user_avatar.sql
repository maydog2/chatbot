-- Add optional avatar_data_url to users.

ALTER TABLE users
  ADD COLUMN IF NOT EXISTS avatar_data_url TEXT;

