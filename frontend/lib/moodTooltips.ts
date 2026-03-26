/** Short: how this mood nudges the bot’s reply (tone, length, warmth). Matches backend VALID_MOODS. */

export const MOOD_TOOLTIPS: Record<string, string> = {
  Calm: "Even tone—no big emotional swings; won’t force jokes or heavy feelings unless you open that.",
  Quiet: "Shorter, cooler replies; less chit-chat and less warmth on the surface.",
  Happy: "More upbeat—lighter words, agreement, and playful riffing on what you said.",
  Irritated:
    "Short, sharp, less patient—may go cold or push back; avoids default therapy-style comfort unless the character demands it.",
  Playful: "More banter—teasing, jokes, looser tone; less formal distance.",
  Tired: "Flat and brief—low energy, simpler answers, less initiative to carry the chat.",
};

export function moodTooltip(mood: string | undefined | null): string {
  const m = (mood ?? "").trim();
  if (m && MOOD_TOOLTIPS[m]) return MOOD_TOOLTIPS[m];
  return m
    ? `“${m}” nudges tone and length this turn (from relationship + chat).`
    : "Mood nudges tone and length each turn (from relationship + chat).";
}
