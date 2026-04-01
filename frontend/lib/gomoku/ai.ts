/**
 * Gomoku AI: candidate moves + threat heuristics (no deep minimax).
 * Step 1: immediate win; Step 2: block opponent win; Step 3: score threats.
 * Serious ("Standard") mode adds multi-direction combination bonuses, weighted defense vs
 * human double threats, and a shallow one-ply reply scan on the top candidate moves.
 */

import {
  EMPTY,
  GOMOKU_SIZE,
  type Cell,
  hasFiveInARow,
  inBounds,
  randomEmptyCell,
  rcToIndex,
} from "./board";

/** Sentinel for out-of-board cells when scanning a line. */
const OUT = 99 as Cell;

/** Pattern weights (simple table, v1). */
export const SCORE_WIN = 1_000_000;
export const SCORE_LIVE_FOUR = 100_000;
export const SCORE_RUSH_FOUR = 20_000;
export const SCORE_LIVE_THREE = 10_000;
export const SCORE_SLEEP_THREE = 3000;
export const SCORE_LIVE_TWO = 1000;
export const SCORE_SLEEP_TWO = 200;

/** Extra weight for human multi-threat shapes when scoring defense (near–must-block). */
const DEFENSE_MULTI_THREAT_WEIGHT = 1.35;

/** Bonuses when one stone creates independent strong threats in multiple directions. */
const BONUS_DOUBLE_OPEN_THREE = 380_000;
const BONUS_OPEN_THREE_PLUS_FOUR = 720_000;
const BONUS_DOUBLE_FOUR = 920_000;

/** Shallow reply scan: only refine top-K by one-ply opponent threat. */
const LOOKAHEAD_TOP_K = 5;
const LOOKAHEAD_WEIGHT = 0.14;

export type PatternKind =
  | "win"
  | "live_four"
  | "rush_four"
  | "live_three"
  | "sleep_three"
  | "live_two"
  | "sleep_two"
  | "none";

export function scorePattern(kind: PatternKind): number {
  switch (kind) {
    case "win":
      return SCORE_WIN;
    case "live_four":
      return SCORE_LIVE_FOUR;
    case "rush_four":
      return SCORE_RUSH_FOUR;
    case "live_three":
      return SCORE_LIVE_THREE;
    case "sleep_three":
      return SCORE_SLEEP_THREE;
    case "live_two":
      return SCORE_LIVE_TWO;
    case "sleep_two":
      return SCORE_SLEEP_TWO;
    default:
      return 0;
  }
}

export function isValidMove(board: Cell[], row: number, col: number): boolean {
  if (!inBounds(row, col)) return false;
  return board[rcToIndex(row, col)] === EMPTY;
}

/** True if `player` at (row,col) completes a straight five (same as game rules). */
export function checkWinner(board: Cell[], row: number, col: number, player: Cell): boolean {
  if (player === EMPTY) return false;
  const i = rcToIndex(row, col);
  const next = board.slice();
  next[i] = player;
  return hasFiveInARow(next, row, col, player);
}

function cellAt(board: Cell[], row: number, col: number): Cell {
  if (!inBounds(row, col)) return OUT;
  return board[rcToIndex(row, col)];
}

/**
 * Empty board → center neighborhood (random among a small set).
 * Otherwise → empty cells within Chebyshev ≤2 OR Manhattan ≤2 of some occupied cell (union).
 */
export function getCandidateMoves(board: Cell[], rng: () => number = Math.random): { row: number; col: number }[] {
  const occupied: { row: number; col: number }[] = [];
  for (let r = 0; r < GOMOKU_SIZE; r++) {
    for (let c = 0; c < GOMOKU_SIZE; c++) {
      if (board[rcToIndex(r, c)] !== EMPTY) occupied.push({ row: r, col: c });
    }
  }

  if (occupied.length === 0) {
    const cx = (GOMOKU_SIZE - 1) / 2;
    const pool: { row: number; col: number }[] = [];
    for (let r = 0; r < GOMOKU_SIZE; r++) {
      for (let c = 0; c < GOMOKU_SIZE; c++) {
        if (Math.abs(r - cx) + Math.abs(c - cx) <= 2) pool.push({ row: r, col: c });
      }
    }
    if (pool.length === 0) return [{ row: Math.floor(cx), col: Math.floor(cx) }];
    return [pool[Math.floor(rng() * pool.length)]];
  }

  const cand = new Set<string>();
  for (const p of occupied) {
    for (let dr = -2; dr <= 2; dr++) {
      for (let dc = -2; dc <= 2; dc++) {
        const r = p.row + dr;
        const c = p.col + dc;
        if (!inBounds(r, c)) continue;
        const cheb = Math.max(Math.abs(dr), Math.abs(dc));
        const manh = Math.abs(dr) + Math.abs(dc);
        if (cheb > 2 && manh > 2) continue;
        if (board[rcToIndex(r, c)] === EMPTY) cand.add(`${r},${c}`);
      }
    }
  }

  const out: { row: number; col: number }[] = [];
  cand.forEach((k) => {
    const [r, c] = k.split(",").map(Number);
    out.push({ row: r, col: c });
  });
  return out;
}

function isOpenEnd(v: Cell): boolean {
  return v === EMPTY;
}

type DirPattern = { score: number; kind: PatternKind };

function patternRank(kind: PatternKind): number {
  const order: PatternKind[] = [
    "none",
    "sleep_two",
    "live_two",
    "sleep_three",
    "live_three",
    "rush_four",
    "live_four",
    "win",
  ];
  return order.indexOf(kind);
}

/**
 * Straight run through `centerIdx` along `line`; board already includes the hypothetical move at center.
 */
function straightPatternOnLine(line: Cell[], centerIdx: number, player: Cell): DirPattern {
  let left = 0;
  for (let i = centerIdx - 1; i >= 0 && line[i] === player; i--) left++;
  let right = 0;
  for (let i = centerIdx + 1; i < line.length && line[i] === player; i++) right++;
  const run = 1 + left + right;

  let li = centerIdx - left - 1;
  const leftCell = li >= 0 ? line[li] : OUT;
  let ri = centerIdx + right + 1;
  const rightCell = ri < line.length ? line[ri] : OUT;

  const leftOpen = isOpenEnd(leftCell);
  const rightOpen = isOpenEnd(rightCell);

  if (run >= 5) return { score: scorePattern("win"), kind: "win" };
  if (run === 4) {
    if (leftOpen && rightOpen) return { score: scorePattern("live_four"), kind: "live_four" };
    if (leftOpen || rightOpen) return { score: scorePattern("rush_four"), kind: "rush_four" };
    return { score: 0, kind: "none" };
  }
  if (run === 3) {
    if (leftOpen && rightOpen) return { score: scorePattern("live_three"), kind: "live_three" };
    if (leftOpen || rightOpen) return { score: scorePattern("sleep_three"), kind: "sleep_three" };
    return { score: scorePattern("sleep_three") / 2, kind: "sleep_three" };
  }
  if (run === 2) {
    if (leftOpen && rightOpen) return { score: scorePattern("live_two"), kind: "live_two" };
    if (leftOpen || rightOpen) return { score: scorePattern("sleep_two"), kind: "sleep_two" };
    return { score: scorePattern("sleep_two") / 2, kind: "sleep_two" };
  }
  return { score: 0, kind: "none" };
}

function opponentOf(player: Cell): Cell {
  return player === 1 ? 2 : 1;
}

/**
 * Sliding windows of length 5 along the line: 4 own + 1 empty (jump) including center as own.
 * Distinguish live-ish vs rush-ish from extension cells outside the window.
 */
function jumpPatternOnLine(line: Cell[], centerIdx: number, player: Cell): DirPattern {
  let best: DirPattern = { score: 0, kind: "none" };
  const opp = opponentOf(player);

  for (let w = 0; w <= line.length - 5; w++) {
    if (centerIdx < w || centerIdx >= w + 5) continue;

    let pc = 0;
    let ec = 0;
    let hasOpp = false;
    for (let j = 0; j < 5; j++) {
      const v = line[w + j];
      if (v === player) pc++;
      else if (v === EMPTY) ec++;
      else if (v === OUT || v === opp) hasOpp = true;
    }
    if (hasOpp) continue;
    if (line[centerIdx] !== player) continue;
    if (pc === 4 && ec === 1) {
      const leftExt = w - 1 >= 0 ? line[w - 1] : OUT;
      const rightExt = w + 5 < line.length ? line[w + 5] : OUT;
      const leftOpen = isOpenEnd(leftExt);
      const rightOpen = isOpenEnd(rightExt);
      const cand: DirPattern = leftOpen && rightOpen
        ? { score: scorePattern("live_four"), kind: "live_four" }
        : leftOpen || rightOpen
          ? { score: scorePattern("rush_four"), kind: "rush_four" }
          : { score: 0, kind: "none" };
      if (cand.score > best.score) best = cand;
      else if (cand.score === best.score && cand.score > 0 && patternRank(cand.kind) > patternRank(best.kind)) best = cand;
    }
  }
  return best;
}

/** Build a line of cells along (dr,dc) with radius 5; center at index 5 = (row,col). */
function extractLine(board: Cell[], row: number, col: number, dr: number, dc: number): Cell[] {
  const line: Cell[] = [];
  for (let k = -5; k <= 5; k++) {
    const r = row + k * dr;
    const c = col + k * dc;
    line.push(cellAt(board, r, c));
  }
  return line;
}

const DIRS: [number, number][] = [
  [0, 1],
  [1, 0],
  [1, 1],
  [1, -1],
];

function mergeDirPatterns(a: DirPattern, b: DirPattern): DirPattern {
  if (a.score > b.score) return a;
  if (b.score > a.score) return b;
  if (a.score === 0) return { score: 0, kind: "none" };
  return patternRank(a.kind) >= patternRank(b.kind) ? a : b;
}

/**
 * Max straight + jump threat along one axis; returns value and winning pattern kind for that axis.
 */
export function directionThreat(
  board: Cell[],
  row: number,
  col: number,
  dr: number,
  dc: number,
  player: Cell
): DirPattern {
  const line = extractLine(board, row, col, dr, dc);
  const centerIdx = 5;
  const straight = straightPatternOnLine(line, centerIdx, player);
  const jump = jumpPatternOnLine(line, centerIdx, player);
  return mergeDirPatterns(straight, jump);
}

/** Max straight + jump threat along one axis (one direction vector). */
export function directionValue(board: Cell[], row: number, col: number, dr: number, dc: number, player: Cell): number {
  return directionThreat(board, row, col, dr, dc, player).score;
}

export type MoveThreatProfile = {
  /** Sum of per-direction scores (same as legacy `evaluatePoint`). */
  baseSum: number;
  /** Dominant pattern kind per axis: horizontal, vertical, main diagonal, anti-diagonal. */
  dirKinds: PatternKind[];
  dirScores: number[];
};

/**
 * Per-direction threats and summed base score (no multi-direction combination bonus).
 * `board` must already contain the stone at (row,col) for analysis.
 */
export function evaluatePointDirections(board: Cell[], row: number, col: number, player: Cell): MoveThreatProfile {
  if (player === EMPTY) {
    return { baseSum: 0, dirKinds: ["none", "none", "none", "none"], dirScores: [0, 0, 0, 0] };
  }
  const dirScores: number[] = [];
  const dirKinds: PatternKind[] = [];
  let baseSum = 0;
  for (const [dr, dc] of DIRS) {
    const d = directionThreat(board, row, col, dr, dc, player);
    dirScores.push(d.score);
    dirKinds.push(d.kind);
    baseSum += d.score;
  }
  return { baseSum, dirKinds, dirScores };
}

/**
 * Large bonus when one move creates two strong independent lines (double three, three+four, double four).
 */
export function multiThreatCombinationBonus(dirKinds: PatternKind[]): number {
  let nLiveThree = 0;
  let nFour = 0;
  for (const k of dirKinds) {
    if (k === "live_three") nLiveThree++;
    if (k === "live_four" || k === "rush_four") nFour++;
  }
  if (nFour >= 2) return BONUS_DOUBLE_FOUR;
  if (nFour >= 1 && nLiveThree >= 1) return BONUS_OPEN_THREE_PLUS_FOUR;
  if (nLiveThree >= 2) return BONUS_DOUBLE_OPEN_THREE;
  return 0;
}

function totalThreatHeuristic(profile: MoveThreatProfile): number {
  return profile.baseSum + multiThreatCombinationBonus(profile.dirKinds);
}

/**
 * If `player` plays at (row,col), sum heuristic scores over four directions.
 * `board` must already contain that stone at (row,col) for analysis.
 */
export function evaluatePoint(board: Cell[], row: number, col: number, player: Cell): number {
  return evaluatePointDirections(board, row, col, player).baseSum;
}

function maxOpponentReplyThreat(board: Cell[], opp: Cell, rng: () => number): number {
  const candidates = getCandidateMoves(board, rng);
  let best = 0;
  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;
    const next = board.slice();
    next[rcToIndex(row, col)] = opp;
    const prof = evaluatePointDirections(next, row, col, opp);
    best = Math.max(best, totalThreatHeuristic(prof));
  }
  return best;
}

/** Manhattan distance from cell to geometric board center — tie-break (prefer smaller). */
function centrality(row: number, col: number): number {
  const cx = (GOMOKU_SIZE - 1) / 2;
  return Math.abs(row - cx) + Math.abs(col - cx);
}

export type ChooseAiMoveOptions = {
  attackWeight?: number;
  defenseWeight?: number;
  rng?: () => number;
};

type ScoredMove = { row: number; col: number; score: number; cent: number };

function pickAmongBestScore(
  scored: ScoredMove[],
  rng: () => number
): { row: number; col: number } | null {
  if (scored.length === 0) return null;
  let bestScore = -Infinity;
  for (const s of scored) bestScore = Math.max(bestScore, s.score);
  const winners = scored.filter((s) => s.score === bestScore);
  winners.sort((a, b) => a.cent - b.cent);
  const bestCent = winners[0].cent;
  const centTies = winners.filter((s) => s.cent === bestCent);
  if (centTies.length === 1) return { row: centTies[0].row, col: centTies[0].col };
  const pick = centTies[Math.floor(rng() * centTies.length)]!;
  return { row: pick.row, col: pick.col };
}

/**
 * Easy ("relaxed"): same pipeline as pre-Standard AI — win → block → sum of directional
 * `evaluatePoint` only (no multi-threat bonuses, no lookahead).
 */
export function chooseEasyMove(
  board: Cell[],
  aiPlayer: Cell,
  humanPlayer: Cell,
  options: ChooseAiMoveOptions = {}
): { row: number; col: number } | null {
  const attackWeight = options.attackWeight ?? 1.0;
  const defenseWeight = options.defenseWeight ?? 1.1;
  const rng = options.rng ?? Math.random;

  const candidates = getCandidateMoves(board, rng);
  if (candidates.length === 0) return null;

  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;
    if (checkWinner(board, row, col, aiPlayer)) return { row, col };
  }

  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;
    if (checkWinner(board, row, col, humanPlayer)) return { row, col };
  }

  const scored: ScoredMove[] = [];
  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;

    const attackBoard = board.slice();
    attackBoard[rcToIndex(row, col)] = aiPlayer;
    const attackScore = evaluatePoint(attackBoard, row, col, aiPlayer);

    const defenseBoard = board.slice();
    defenseBoard[rcToIndex(row, col)] = humanPlayer;
    const defenseScore = evaluatePoint(defenseBoard, row, col, humanPlayer);

    const score = attackScore * attackWeight + defenseScore * defenseWeight;
    scored.push({ row, col, score, cent: centrality(row, col) });
  }

  return pickAmongBestScore(scored, rng);
}

/**
 * Standard ("serious"): win → block → enhanced threat scoring, defense weight on human
 * multi-threats, shallow lookahead on top candidates.
 */
export function chooseAiMove(
  board: Cell[],
  aiPlayer: Cell,
  humanPlayer: Cell,
  options: ChooseAiMoveOptions = {}
): { row: number; col: number } | null {
  const attackWeight = options.attackWeight ?? 1.0;
  const defenseWeight = options.defenseWeight ?? 1.1;
  const rng = options.rng ?? Math.random;

  const candidates = getCandidateMoves(board, rng);
  if (candidates.length === 0) return null;

  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;
    if (checkWinner(board, row, col, aiPlayer)) return { row, col };
  }

  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;
    if (checkWinner(board, row, col, humanPlayer)) return { row, col };
  }

  type PreScored = { row: number; col: number; preScore: number; cent: number };
  const preScored: PreScored[] = [];

  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;

    const attackBoard = board.slice();
    attackBoard[rcToIndex(row, col)] = aiPlayer;
    const attackProf = evaluatePointDirections(attackBoard, row, col, aiPlayer);
    const attackTotal = totalThreatHeuristic(attackProf);

    const defenseBoard = board.slice();
    defenseBoard[rcToIndex(row, col)] = humanPlayer;
    const defenseProf = evaluatePointDirections(defenseBoard, row, col, humanPlayer);
    const defenseMulti = multiThreatCombinationBonus(defenseProf.dirKinds);
    const defenseTotal =
      defenseProf.baseSum + defenseMulti * DEFENSE_MULTI_THREAT_WEIGHT;

    const preScore = attackTotal * attackWeight + defenseTotal * defenseWeight;
    preScored.push({ row, col, preScore, cent: centrality(row, col) });
  }

  if (preScored.length === 0) return null;

  const sortedPre = [...preScored].sort((a, b) => b.preScore - a.preScore || a.cent - b.cent);
  const topKRows = new Set<number>();
  for (let i = 0; i < Math.min(LOOKAHEAD_TOP_K, sortedPre.length); i++) {
    topKRows.add(sortedPre[i].row * GOMOKU_SIZE + sortedPre[i].col);
  }

  const scored: ScoredMove[] = preScored.map((p) => {
    let score = p.preScore;
    const key = p.row * GOMOKU_SIZE + p.col;
    if (topKRows.has(key)) {
      const attackBoard = board.slice();
      attackBoard[rcToIndex(p.row, p.col)] = aiPlayer;
      const reply = maxOpponentReplyThreat(attackBoard, humanPlayer, rng);
      score -= LOOKAHEAD_WEIGHT * reply;
    }
    return { row: p.row, col: p.col, score, cent: p.cent };
  });

  return pickAmongBestScore(scored, rng);
}

export type GomokuAiDifficulty = "relaxed" | "serious";

/**
 * Relaxed = easy heuristic (legacy). Serious = Standard AI.
 */
export function chooseMoveByDifficulty(
  board: Cell[],
  aiPlayer: Cell,
  humanPlayer: Cell,
  difficulty: GomokuAiDifficulty,
  options: ChooseAiMoveOptions = {}
): { row: number; col: number } | null {
  const rng = options.rng ?? Math.random;
  if (difficulty === "relaxed") {
    return chooseEasyMove(board, aiPlayer, humanPlayer, options) ?? randomEmptyCell(board, rng);
  }
  return chooseAiMove(board, aiPlayer, humanPlayer, options) ?? randomEmptyCell(board, rng);
}

type Rc = { row: number; col: number };

function threatHeuristicAfterPlacing(board: Cell[], row: number, col: number, player: Cell): number {
  const next = board.slice();
  next[rcToIndex(row, col)] = player;
  const prof = evaluatePointDirections(next, row, col, player);
  return prof.baseSum + multiThreatCombinationBonus(prof.dirKinds);
}

function topCandidateMoves(
  board: Cell[],
  player: Cell,
  limit: number,
  rng: () => number
): Rc[] {
  const candidates = getCandidateMoves(board, rng);
  const scored: { row: number; col: number; h: number }[] = [];
  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;
    const h = threatHeuristicAfterPlacing(board, row, col, player);
    scored.push({ row, col, h });
  }
  scored.sort((a, b) => b.h - a.h);
  return scored.slice(0, Math.max(1, limit)).map(({ row, col }) => ({ row, col }));
}

function existsImmediateWin(board: Cell[], player: Cell, rng: () => number): boolean {
  const candidates = getCandidateMoves(board, rng);
  for (const { row, col } of candidates) {
    if (!isValidMove(board, row, col)) continue;
    if (checkWinner(board, row, col, player)) return true;
  }
  return false;
}

/**
 * Heuristic "mate in 2" detector.
 *
 * Interprets "in 2" as: attacker can force a win on their second move, after
 * defender plays now, attacker plays, defender replies, attacker wins.
 *
 * Notes:
 * - Uses local candidate generation (`getCandidateMoves`) + top-K pruning; this
 *   is intended for UI flavor (restart remarks), not perfect play proofs.
 */
export function isAttackerWinInTwoInevitableFromDefenderTurn(
  board: Cell[],
  attacker: Cell,
  defender: Cell,
  opts: {
    rng?: () => number;
    /** How many defender first moves to consider. */
    defenderMoveCap?: number;
    /** How many attacker setup moves to consider after each defender move. */
    attackerMoveCap?: number;
    /** How many defender replies to consider after attacker setup. */
    defenderReplyCap?: number;
  } = {}
): boolean {
  const rng = opts.rng ?? Math.random;
  const defenderMoveCap = opts.defenderMoveCap ?? 36;
  const attackerMoveCap = opts.attackerMoveCap ?? 18;
  const defenderReplyCap = opts.defenderReplyCap ?? 28;

  const defenderMoves = topCandidateMoves(board, defender, defenderMoveCap, rng);

  // If defender has *any* move that avoids the forced sequence (within our search),
  // then it's not "inevitable".
  for (const d0 of defenderMoves) {
    if (!isValidMove(board, d0.row, d0.col)) continue;
    const afterD0 = board.slice();
    afterD0[rcToIndex(d0.row, d0.col)] = defender;

    let attackerHasForcingLine = false;
    const attackerSetups = topCandidateMoves(afterD0, attacker, attackerMoveCap, rng);
    for (const a1 of attackerSetups) {
      if (!isValidMove(afterD0, a1.row, a1.col)) continue;
      if (checkWinner(afterD0, a1.row, a1.col, attacker)) {
        attackerHasForcingLine = true;
        break;
      }

      const afterA1 = afterD0.slice();
      afterA1[rcToIndex(a1.row, a1.col)] = attacker;

      const defenderReplies = topCandidateMoves(afterA1, defender, defenderReplyCap, rng);
      let allRepliesLose = true;
      for (const d2 of defenderReplies) {
        if (!isValidMove(afterA1, d2.row, d2.col)) continue;
        const afterD2 = afterA1.slice();
        afterD2[rcToIndex(d2.row, d2.col)] = defender;
        if (!existsImmediateWin(afterD2, attacker, rng)) {
          allRepliesLose = false;
          break;
        }
      }

      if (allRepliesLose) {
        attackerHasForcingLine = true;
        break;
      }
    }

    if (!attackerHasForcingLine) return false;
  }

  return defenderMoves.length > 0;
}
