import type { GomokuAiDifficulty } from "./ai";

/** In-memory minigame state; drives ephemeral LLM context (not persisted). */
export type ActiveGomokuGame = {
  type: "gomoku";
  difficulty: GomokuAiDifficulty;
  current_turn: "user" | "bot";
  bot_side: "white";
};
