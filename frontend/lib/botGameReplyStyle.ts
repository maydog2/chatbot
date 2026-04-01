/** Stored as bot.personality; used for in-app game invite lines (Gomoku, etc.). */

export type GameReplyStyle = "playful" | "cool" | "gentle" | "tsundere";

export const DEFAULT_GAME_REPLY_STYLE: GameReplyStyle = "gentle";

export const GAME_REPLY_STYLE_OPTIONS: { key: GameReplyStyle }[] = [
  { key: "playful" },
  { key: "cool" },
  { key: "gentle" },
  { key: "tsundere" },
];

export function normalizeGameReplyStyle(
  raw: string | null | undefined
): GameReplyStyle {
  const s = (raw ?? "").trim().toLowerCase();
  if (s === "playful" || s === "cool" || s === "gentle" || s === "tsundere") {
    return s;
  }
  if (s === "lively") return "playful";
  if (s === "cold") return "cool";
  if (s === "default") return "gentle";
  return DEFAULT_GAME_REPLY_STYLE;
}
