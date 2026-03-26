-- Legacy databases may lack a unique index on users.username (schema.sql / reset.sql already define UNIQUE).
-- Safe to run multiple times.
CREATE UNIQUE INDEX IF NOT EXISTS users_username_key ON users (username);
