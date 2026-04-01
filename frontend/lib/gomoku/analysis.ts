/**
 * Position summary for Gomoku (layer 2): phase, coarse eval, urgency, threats, events.
 * Board representation matches `board.ts`: row-major flat `Cell[]`, length `GOMOKU_CELL_COUNT`.
 */

import {
  EMPTY,
  GOMOKU_CELL_COUNT,
  GOMOKU_SIZE,
  BLACK,
  WHITE,
  hasFiveInARow,
  rcToIndex,
  type Cell,
} from "./board";
import { evaluatePointDirections, type PatternKind } from "./ai";

export type GomokuPhase = "opening" | "midgame" | "endgame";

export type GomokuEval =
  | "even"
  | "user_slightly_ahead"
  | "bot_slightly_ahead"
  | "user_winning"
  | "bot_winning";

export type GomokuUrgency =
  | "none"
  | "bot_must_defend"
  | "user_must_defend"
  | "bot_can_finish"
  | "user_can_finish";

export type GomokuThreatKind = "open_four" | "closed_four" | "open_three";

export type GomokuPositionEvent =
  | "user_created_threat"
  | "bot_created_threat"
  | "user_blocked_bot_threat"
  | "bot_blocked_user_threat"
  | "position_is_tense";

export type Side = "user" | "bot";

/** Logical stone color for API; maps to `Cell` via `stoneToCell`. */
export type Stone = "black" | "white";

/** Intersection: `x` = column index, `y` = row index (0-based), aligned with `board[y][x]` style. */
export type Point = { x: number; y: number };

/** Set when the UI has declared the match finished (five in a row or draw). */
export type GomokuMatchResult = "user_win" | "bot_win" | "draw";

export type GomokuPositionSummary = {
  phase: GomokuPhase;
  eval: GomokuEval;
  urgency: GomokuUrgency;

  move_count: number;

  last_move: Point | null;
  last_move_by: Side | null;
  current_turn: Side;

  /** True when the game board shows win/draw (authoritative for side-chat). */
  game_over: boolean;
  /** Who won, from user/bot perspective; null only when not `game_over`. */
  match_result: GomokuMatchResult | null;

  threats: {
    user: GomokuThreatKind[];
    bot: GomokuThreatKind[];
  };

  winning_points: {
    user: Point[];
    bot: Point[];
  };

  events: GomokuPositionEvent[];
};

/** Emitted by the board UI when the grid or turn/outcome changes; feeds `analyzePosition`. */
export type GomokuBoardSnapshot = {
  board: Cell[];
  last_move: Point | null;
  last_move_by: Side | null;
  /** Side to move next (from the board clock); stale when `game_over`. */
  next_to_move: Side;
  game_over: boolean;
  /** From board rules: black=user, white=bot. */
  match_result: GomokuMatchResult | null;
};

export type AnalyzePositionInput = {
  /** Row-major flat cells, same as `emptyBoard()` / `tryPlay` in `board.ts`. */
  board: Cell[];
  current_turn: Side;
  last_move: Point | null;
  last_move_by: Side | null;
  user_stone: Stone;
  bot_stone: Stone;
  game_over: boolean;
  match_result: GomokuMatchResult | null;
  prev_summary?: GomokuPositionSummary | null;
};

export function analyzePosition(input: AnalyzePositionInput): GomokuPositionSummary {
  assertFlatBoard(input.board);

  const move_count = getMoveCount(input.board);
  const phase = derivePhase(move_count);

  const userCell = stoneToCell(input.user_stone);
  const botCell = stoneToCell(input.bot_stone);

  const userWinningPoints = findWinningPointsForSide(input.board, userCell);
  const botWinningPoints = findWinningPointsForSide(input.board, botCell);

  const userThreats = detectThreatKindsForSide(input.board, userCell);
  const botThreats = detectThreatKindsForSide(input.board, botCell);

  const urgency = deriveUrgency({
    userWinningPoints,
    botWinningPoints,
    userThreats,
    botThreats,
  });

  const evalResult = deriveEval({
    userWinningPoints,
    botWinningPoints,
    userThreats,
    botThreats,
  });

  const partial: Omit<GomokuPositionSummary, "events"> = {
    phase,
    eval: evalResult,
    urgency,
    move_count,
    last_move: input.last_move,
    last_move_by: input.last_move_by,
    current_turn: input.current_turn,
    game_over: input.game_over,
    match_result: input.match_result,
    threats: {
      user: userThreats,
      bot: botThreats,
    },
    winning_points: {
      user: userWinningPoints,
      bot: botWinningPoints,
    },
  };

  const events = deriveEvents(input.prev_summary ?? null, partial);

  return {
    ...partial,
    events,
  };
}

function assertFlatBoard(board: Cell[]): void {
  if (board.length !== GOMOKU_CELL_COUNT) {
    throw new Error(`analyzePosition: expected board length ${GOMOKU_CELL_COUNT}, got ${board.length}`);
  }
}

function stoneToCell(s: Stone): Cell {
  return s === "black" ? BLACK : WHITE;
}

function getMoveCount(board: Cell[]): number {
  let count = 0;
  for (let i = 0; i < board.length; i++) {
    if (board[i] !== EMPTY) count += 1;
  }
  return count;
}

function derivePhase(moveCount: number): GomokuPhase {
  if (moveCount < 8) return "opening";
  if (moveCount < 28) return "midgame";
  return "endgame";
}

function findWinningPointsForSide(board: Cell[], stone: Cell): Point[] {
  const points: Point[] = [];

  for (let y = 0; y < GOMOKU_SIZE; y += 1) {
    for (let x = 0; x < GOMOKU_SIZE; x += 1) {
      if (board[rcToIndex(y, x)] !== EMPTY) continue;

      const next = cloneBoard(board);
      next[rcToIndex(y, x)] = stone;

      if (hasFiveInARow(next, y, x, stone)) {
        points.push({ x, y });
      }
    }
  }

  return points;
}

/**
 * Collect threat shapes for `stone` by probing every empty intersection:
 * hypothetically play there (skip immediate wins — those belong in `winning_points`),
 * then reuse `ai` line/jump pattern logic per axis.
 *
 * Mapping: live_four → open_four (活四), rush_four → closed_four (冲四), live_three → open_three (活三).
 */
function detectThreatKindsForSide(board: Cell[], stone: Cell): GomokuThreatKind[] {
  const threats = new Set<GomokuThreatKind>();

  for (let y = 0; y < GOMOKU_SIZE; y += 1) {
    for (let x = 0; x < GOMOKU_SIZE; x += 1) {
      if (board[rcToIndex(y, x)] !== EMPTY) continue;

      const next = cloneBoard(board);
      next[rcToIndex(y, x)] = stone;

      if (hasFiveInARow(next, y, x, stone)) continue;

      const { dirKinds } = evaluatePointDirections(next, y, x, stone);
      for (const k of dirKinds) {
        const mapped = patternKindToThreatKind(k);
        if (mapped) threats.add(mapped);
      }
    }
  }

  return sortThreatKinds(threats);
}

function patternKindToThreatKind(k: PatternKind): GomokuThreatKind | null {
  if (k === "live_four") return "open_four";
  if (k === "rush_four") return "closed_four";
  if (k === "live_three") return "open_three";
  return null;
}

const THREAT_KIND_ORDER: GomokuThreatKind[] = ["open_four", "closed_four", "open_three"];

function sortThreatKinds(threats: Set<GomokuThreatKind>): GomokuThreatKind[] {
  return THREAT_KIND_ORDER.filter((k) => threats.has(k));
}

function deriveUrgency(args: {
  userWinningPoints: Point[];
  botWinningPoints: Point[];
  userThreats: GomokuThreatKind[];
  botThreats: GomokuThreatKind[];
}): GomokuUrgency {
  const { userWinningPoints, botWinningPoints, userThreats, botThreats } = args;

  if (botWinningPoints.length > 0) return "bot_can_finish";
  if (userWinningPoints.length > 0) return "user_can_finish";

  if (includesAny(userThreats, ["open_four", "closed_four", "open_three"])) {
    return "bot_must_defend";
  }

  if (includesAny(botThreats, ["open_four", "closed_four", "open_three"])) {
    return "user_must_defend";
  }

  return "none";
}

function deriveEval(args: {
  userWinningPoints: Point[];
  botWinningPoints: Point[];
  userThreats: GomokuThreatKind[];
  botThreats: GomokuThreatKind[];
}): GomokuEval {
  const userScore = scoreSide(args.userWinningPoints, args.userThreats);
  const botScore = scoreSide(args.botWinningPoints, args.botThreats);
  const diff = botScore - userScore;

  if (botScore >= 1000 && diff >= 400) return "bot_winning";
  if (userScore >= 1000 && diff <= -400) return "user_winning";

  if (diff >= 120) return "bot_slightly_ahead";
  if (diff <= -120) return "user_slightly_ahead";

  return "even";
}

function scoreSide(winningPoints: Point[], threats: GomokuThreatKind[]): number {
  let score = 0;

  score += winningPoints.length * 1000;

  for (const t of threats) {
    if (t === "open_four") score += 300;
    else if (t === "closed_four") score += 180;
    else if (t === "open_three") score += 80;
  }

  return score;
}

function deriveEvents(
  prev: GomokuPositionSummary | null,
  next: Omit<GomokuPositionSummary, "events">
): GomokuPositionEvent[] {
  const events = new Set<GomokuPositionEvent>();

  if (!prev) {
    if (isTense(next)) events.add("position_is_tense");
    return Array.from(events);
  }

  const prevUserHasThreat = prev.threats.user.length > 0 || prev.winning_points.user.length > 0;
  const prevBotHasThreat = prev.threats.bot.length > 0 || prev.winning_points.bot.length > 0;
  const nextUserHasThreat = next.threats.user.length > 0 || next.winning_points.user.length > 0;
  const nextBotHasThreat = next.threats.bot.length > 0 || next.winning_points.bot.length > 0;

  if (!prevUserHasThreat && nextUserHasThreat) {
    events.add("user_created_threat");
  }
  if (!prevBotHasThreat && nextBotHasThreat) {
    events.add("bot_created_threat");
  }
  if (prevBotHasThreat && !nextBotHasThreat) {
    events.add("user_blocked_bot_threat");
  }
  if (prevUserHasThreat && !nextUserHasThreat) {
    events.add("bot_blocked_user_threat");
  }

  if (isTense(next)) {
    events.add("position_is_tense");
  }

  return Array.from(events);
}

function isTense(summary: Omit<GomokuPositionSummary, "events">): boolean {
  const userDanger = summary.threats.user.length > 0 || summary.winning_points.user.length > 0;
  const botDanger = summary.threats.bot.length > 0 || summary.winning_points.bot.length > 0;
  return userDanger || botDanger;
}

function includesAny<T extends string>(arr: T[], targets: readonly T[]): boolean {
  return targets.some((t) => arr.includes(t));
}

function cloneBoard(board: Cell[]): Cell[] {
  return board.slice();
}
