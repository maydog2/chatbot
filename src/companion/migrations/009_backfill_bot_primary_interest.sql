-- Older bots may have NULL primary_interest; app now requires a primary for new saves.
UPDATE bots
SET primary_interest = 'self_growth'
WHERE primary_interest IS NULL OR btrim(primary_interest) = '';
