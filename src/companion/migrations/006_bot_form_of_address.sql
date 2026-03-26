-- How the bot should address the user (e.g. "Master", "sensei"); optional TEXT.
ALTER TABLE bots ADD COLUMN IF NOT EXISTS form_of_address TEXT;
