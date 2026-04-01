/**
 * When the Gomoku companion should speak (non-LLM gate) and which reaction flavor to prefer.
 */

import type { GameReplyStyle } from "@/lib/botGameReplyStyle";
import type { GomokuPositionEvent, GomokuPositionSummary } from "./analysis";

/** Only values returned by `decideGomokuDialogue` today. */
export type GomokuReactionType =
  | "react_to_threat"
  | "apply_pressure"
  | "light_banter"
  | "endgame_result";

/** Only values returned by `decideGomokuDialogue` today. */
export type GomokuDialogueReason =
  | "user_created_threat"
  | "user_can_finish"
  | "bot_created_threat"
  | "bot_can_finish"
  | "user_win"
  | "bot_win"
  | "none";

export type GomokuDialogueDecision = {
  shouldSpeak: boolean;
  reaction: GomokuReactionType | null;
  reason: GomokuDialogueReason;
  style: GameReplyStyle;
};

export type DecideGomokuDialogueInput = {
  summary: GomokuPositionSummary | null;
  style: GameReplyStyle;
  /** Prefer explicit flag; falls back to `summary.game_over` when omitted/false. */
  game_over?: boolean;
};

export function decideGomokuDialogue(input: DecideGomokuDialogueInput): GomokuDialogueDecision {
  const { summary, style, game_over: gameOverInput = false } = input;

  if (!summary) {
    return silent(style);
  }

  const gameOver = gameOverInput || summary.game_over;

  // Match finished (draw / unknown → no scripted line)
  if (gameOver) {
    const mr = summary.match_result;
    if (mr !== "user_win" && mr !== "bot_win") {
      return silent(style);
    }
    return {
      shouldSpeak: true,
      reaction: "endgame_result",
      reason: mr === "user_win" ? "user_win" : "bot_win",
      style,
    };
  }

  // Early phase: stay silent.
  if (summary.phase === "opening") return silent(style);

  // User can win next
  if (summary.urgency === "user_can_finish") {
    return {
      shouldSpeak: true,
      reaction: "react_to_threat",
      reason: "user_can_finish",
      style,
    };
  }

  const userThreats = summary.threats?.user ?? [];
  const botThreats = summary.threats?.bot ?? [];

  // Bot can win next
  if (summary.urgency === "bot_can_finish") {
    return pickPreferred(style, [
      { reaction: "apply_pressure", reason: "bot_can_finish" },
      { reaction: "light_banter", reason: "bot_can_finish" },
    ]);
  }

  // Imminent kill patterns beyond immediate wins (approximation; see analysis limits).
  const userImminent =
    userThreats.includes("open_four") ||
    (userThreats.includes("closed_four") && userThreats.includes("open_three"));
  if (userImminent && hasEvent(summary.events, "user_created_threat")) {
    return {
      shouldSpeak: true,
      reaction: "react_to_threat",
      reason: "user_created_threat",
      style,
    };
  }

  const botImminent =
    botThreats.includes("open_four") ||
    (botThreats.includes("closed_four") && botThreats.includes("open_three"));
  if (botImminent && hasEvent(summary.events, "bot_created_threat")) {
    return pickPreferred(style, [
      { reaction: "apply_pressure", reason: "bot_created_threat" },
      { reaction: "light_banter", reason: "bot_created_threat" },
    ]);
  }

  return silent(style);
}

function silent(style: GameReplyStyle): GomokuDialogueDecision {
  return {
    shouldSpeak: false,
    reaction: null,
    reason: "none",
    style,
  };
}

function hasEvent(events: GomokuPositionEvent[], target: GomokuPositionEvent): boolean {
  return events.includes(target);
}

type ReactionCandidate = {
  reaction: GomokuReactionType;
  reason: GomokuDialogueReason;
};

function pickPreferred(style: GameReplyStyle, candidates: ReactionCandidate[]): GomokuDialogueDecision {
  const ranking = STYLE_REACTION_PRIORITY[style];

  let best = candidates[0]!;
  let bestScore = rankOf(ranking, best.reaction);

  for (let i = 1; i < candidates.length; i += 1) {
    const c = candidates[i]!;
    const score = rankOf(ranking, c.reaction);
    if (score < bestScore) {
      best = c;
      bestScore = score;
    }
  }

  return {
    shouldSpeak: true,
    reaction: best.reaction,
    reason: best.reason,
    style,
  };
}

function rankOf(ranking: GomokuReactionType[], reaction: GomokuReactionType): number {
  const idx = ranking.indexOf(reaction);
  return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
}

const STYLE_REACTION_PRIORITY: Record<GameReplyStyle, GomokuReactionType[]> = {
  playful: ["light_banter", "apply_pressure", "react_to_threat", "endgame_result"],
  cool: ["react_to_threat", "apply_pressure", "endgame_result", "light_banter"],
  gentle: ["react_to_threat", "apply_pressure", "endgame_result", "light_banter"],
  tsundere: ["light_banter", "apply_pressure", "react_to_threat", "endgame_result"],
};

const GOMOKU_POLICY_LINE_VARIANTS = 3;

function policyLineLookupReactionReason(
  reaction: GomokuReactionType,
  reason: GomokuDialogueReason,
): { reaction: GomokuReactionType; reason: GomokuDialogueReason } {
  if (
    reaction === "light_banter" &&
    (reason === "bot_created_threat" || reason === "bot_can_finish")
  ) {
    return { reaction: "apply_pressure", reason };
  }
  return { reaction, reason };
}

/**
 * Resolves a policy decision to localized text, or `null` when the bot should stay silent.
 * `reason === "none"` or missing reaction always yields `null`.
 */
export function pickGomokuPolicyLine(
  decision: GomokuDialogueDecision,
  tr: (key: string) => string,
  rng: () => number,
): string | null {
  if (!decision.shouldSpeak || decision.reason === "none" || !decision.reaction) {
    return null;
  }
  const { reaction, reason, style } = decision;
  const { reaction: lr, reason: rr } = policyLineLookupReactionReason(reaction, reason);
  const v = Math.floor(rng() * GOMOKU_POLICY_LINE_VARIANTS);
  const key = `games.gomokuPolicy.${lr}.${rr}.${style}.${v}`;
  const text = tr(key);
  if (!text || text === key) {
    return null;
  }
  return text;
}
