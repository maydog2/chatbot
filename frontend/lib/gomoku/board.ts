/** Pure Gomoku (five in a row) rules on a square board. No React. */

export const GOMOKU_SIZE = 12;
export const GOMOKU_CELL_COUNT = GOMOKU_SIZE * GOMOKU_SIZE;

export const EMPTY = 0;
export const BLACK = 1;
export const WHITE = 2;

export type Cell = typeof EMPTY | typeof BLACK | typeof WHITE;

export type WinOutcome = "black_win" | "white_win" | "draw" | "ongoing";

export function emptyBoard(): Cell[] {
  return Array.from({ length: GOMOKU_CELL_COUNT }, () => EMPTY);
}

export function rcToIndex(row: number, col: number): number {
  return row * GOMOKU_SIZE + col;
}

export function indexToRC(index: number): { row: number; col: number } {
  return { row: Math.floor(index / GOMOKU_SIZE), col: index % GOMOKU_SIZE };
}

export function inBounds(row: number, col: number): boolean {
  return row >= 0 && row < GOMOKU_SIZE && col >= 0 && col < GOMOKU_SIZE;
}

function countLine(board: Cell[], row: number, col: number, dr: number, dc: number, stone: Cell): number {
  let n = 0;
  let r = row + dr;
  let c = col + dc;
  while (inBounds(r, c) && board[rcToIndex(r, c)] === stone) {
    n += 1;
    r += dr;
    c += dc;
  }
  return n;
}

/** Returns true if this stone completes a line of at least 5 through (row, col). */
export function hasFiveInARow(board: Cell[], row: number, col: number, stone: Cell): boolean {
  if (stone === EMPTY) return false;
  const dirs: [number, number][] = [
    [0, 1],
    [1, 0],
    [1, 1],
    [1, -1],
  ];
  for (const [dr, dc] of dirs) {
    const total = 1 + countLine(board, row, col, dr, dc, stone) + countLine(board, row, col, -dr, -dc, stone);
    if (total >= 5) return true;
  }
  return false;
}

export function boardFull(board: Cell[]): boolean {
  return board.every((x) => x !== EMPTY);
}

export function outcomeAfterMove(board: Cell[], row: number, col: number, stone: Cell): WinOutcome {
  if (hasFiveInARow(board, row, col, stone)) {
    return stone === BLACK ? "black_win" : "white_win";
  }
  if (boardFull(board)) return "draw";
  return "ongoing";
}

export type PlayResult = { board: Cell[]; outcome: WinOutcome };

/** Place `stone` at (row, col) if empty. Returns null if illegal. */
export function tryPlay(board: Cell[], row: number, col: number, stone: Cell): PlayResult | null {
  if (stone === EMPTY || !inBounds(row, col)) return null;
  const i = rcToIndex(row, col);
  if (board[i] !== EMPTY) return null;
  const next = board.slice();
  next[i] = stone;
  return { board: next, outcome: outcomeAfterMove(next, row, col, stone) };
}

export function listEmptyIndices(board: Cell[]): number[] {
  const out: number[] = [];
  for (let i = 0; i < board.length; i++) {
    if (board[i] === EMPTY) out.push(i);
  }
  return out;
}

/** Uniform random empty cell; `rng` defaults to Math.random (0 inclusive, 1 exclusive). */
export function randomEmptyCell(
  board: Cell[],
  rng: () => number = Math.random
): { row: number; col: number } | null {
  const empties = listEmptyIndices(board);
  if (empties.length === 0) return null;
  const pick = empties[Math.floor(rng() * empties.length)];
  return indexToRC(pick);
}
