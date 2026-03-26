/** Keys match backend `companion/interests.py` (English labels only in UI). */
export type InterestKey =
  | "anime"
  | "gaming"
  | "movies"
  | "tv_series"
  | "music"
  | "food"
  | "travel"
  | "history"
  | "tech"
  | "programming"
  | "fitness"
  | "psychology"
  | "books"
  | "writing"
  | "art"
  | "photography"
  | "fashion"
  | "pets"
  | "cars"
  | "business"
  | "finance"
  | "philosophy"
  | "daily_life"
  | "emotions"
  | "relationships"
  | "study"
  | "work"
  | "self_growth";

export type InterestDef = { key: InterestKey; label: string; primaryOk: boolean };

export const BOT_INTERESTS: InterestDef[] = [
  { key: "anime", label: "Anime / ACG", primaryOk: true },
  { key: "gaming", label: "Gaming", primaryOk: true },
  { key: "movies", label: "Movies", primaryOk: true },
  { key: "tv_series", label: "TV series", primaryOk: true },
  { key: "music", label: "Music", primaryOk: true },
  { key: "food", label: "Food", primaryOk: true },
  { key: "travel", label: "Travel", primaryOk: true },
  { key: "history", label: "History", primaryOk: true },
  { key: "tech", label: "Technology", primaryOk: true },
  { key: "programming", label: "Programming / software", primaryOk: true },
  { key: "fitness", label: "Fitness / sports", primaryOk: true },
  { key: "psychology", label: "Psychology", primaryOk: true },
  { key: "books", label: "Reading / books", primaryOk: true },
  { key: "writing", label: "Writing / creative writing", primaryOk: true },
  { key: "art", label: "Drawing / visual art", primaryOk: true },
  { key: "photography", label: "Photography", primaryOk: true },
  { key: "fashion", label: "Fashion / style", primaryOk: true },
  { key: "pets", label: "Pets / animals", primaryOk: true },
  { key: "cars", label: "Cars / motorbikes", primaryOk: true },
  { key: "business", label: "Business / startups", primaryOk: true },
  { key: "finance", label: "Finance / investing", primaryOk: true },
  { key: "philosophy", label: "Philosophy", primaryOk: true },
  { key: "daily_life", label: "Daily life", primaryOk: false },
  { key: "emotions", label: "Emotions / companionship", primaryOk: false },
  { key: "relationships", label: "Relationships", primaryOk: false },
  { key: "study", label: "School / learning", primaryOk: false },
  { key: "work", label: "Work / career", primaryOk: false },
  { key: "self_growth", label: "Lifestyle / self-growth", primaryOk: true },
];

export const PRIMARY_INTEREST_OPTIONS = BOT_INTERESTS.filter((x) => x.primaryOk);
export const SECONDARY_INTEREST_OPTIONS = BOT_INTERESTS;

/** Default primary when creating a bot (first eligible option). */
export const DEFAULT_PRIMARY_INTEREST_KEY = PRIMARY_INTEREST_OPTIONS[0]!.key;

export function interestLabel(key: string): string {
  return BOT_INTERESTS.find((x) => x.key === key)?.label ?? key;
}
