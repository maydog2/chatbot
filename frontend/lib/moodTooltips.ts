/** Short: how this mood nudges the bot’s reply (tone, length, warmth). Matches backend VALID_MOODS. */

import { translations, type Locale } from "./translations";

export function moodTooltip(mood: string | undefined | null, locale: Locale = "en"): string {
  const m = (mood ?? "").trim();
  const pack = translations[locale];
  const key = m ? `mood.${m}` : "";
  if (m && pack[key]) return pack[key];
  const named = pack["mood.fallbackNamed"] ?? translations.en["mood.fallbackNamed"];
  const fallback = pack["mood.fallback"] ?? translations.en["mood.fallback"];
  return m ? named.replace("{m}", m) : fallback;
}
