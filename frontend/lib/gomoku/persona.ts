import type { Bot } from "@/lib/api";
import { normalizeGameReplyStyle, type GameReplyStyle } from "@/lib/botGameReplyStyle";
import type { GomokuAiDifficulty } from "./ai";

function gomokuLineForStyle(tr: (key: string) => string, p: GameReplyStyle): string {
  switch (p) {
    case "tsundere":
      return tr("games.gomokuReplyTsundere");
    case "playful":
      return tr("games.gomokuReplyPlayful");
    case "cool":
      return tr("games.gomokuReplyCool");
    case "gentle":
      return tr("games.gomokuReplyGentle");
    default:
      return tr("games.gomokuReplyGentle");
  }
}

/** In-character one-liner when the user starts Gomoku (no LLM). Uses bot's chosen game reply style. */
export function gomokuPersonaReply(tr: (key: string) => string, bot: Bot): string {
  return gomokuLineForStyle(tr, normalizeGameReplyStyle(bot.personality));
}

export function pickGomokuRestartTauntWinInTwo(
  gameReplyStyle: GameReplyStyle,
  tr: (key: string) => string,
  rng: () => number = Math.random
): string {
  const style = gameReplyStyle;
  const n = Math.floor(rng() * 3);
  return tr(`games.gomokuRestartTaunt.winInTwo.${style}.${n}`);
}

const GOMOKU_FIRST_MOVE_VARIANT_COUNT = 5;

/** One in-character line when the bot plays its first stone after the user's opening move. */
export function pickGomokuFirstMoveLine(
  difficulty: GomokuAiDifficulty,
  style: GameReplyStyle,
  tr: (key: string) => string,
  rng: () => number
): string {
  const diffKey = difficulty === "relaxed" ? "relaxed" : "serious";
  const v = Math.floor(rng() * GOMOKU_FIRST_MOVE_VARIANT_COUNT);
  return tr(`games.gomokuFirstMove.${diffKey}.${style}.${v}`);
}
