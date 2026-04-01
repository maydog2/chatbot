"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GameReplyStyle } from "@/lib/botGameReplyStyle";
import {
  BLACK,
  EMPTY,
  GOMOKU_CELL_COUNT,
  GOMOKU_SIZE,
  WHITE,
  chooseMoveByDifficulty,
  emptyBoard,
  isAttackerWinInTwoInevitableFromDefenderTurn,
  pickGomokuRestartTauntWinInTwo,
  randomEmptyCell,
  tryPlay,
  type Cell,
  type ChooseAiMoveOptions,
  type GomokuAiDifficulty,
  type GomokuBoardSnapshot,
  type GomokuMatchResult,
  type Side,
  type WinOutcome,
} from "@/lib/gomoku";

type Turn = "black" | "white";
type MatchResult = null | "black_win" | "white_win" | "draw";

function terminalFromOutcome(o: WinOutcome): MatchResult {
  if (o === "ongoing") return null;
  return o;
}

export type GomokuBoardProps = {
  /** Remount when a new match starts (e.g. session timestamp). */
  matchKey: number | string;
  tr: (key: string) => string;
  onQuit: () => void;
  onHideBoard: () => void;
  /** Optional AI tuning (e.g. per-bot persona: aggressive vs cautious). */
  aiMoveOptions?: ChooseAiMoveOptions;
  gameReplyStyle: GameReplyStyle;
  aiDifficulty: GomokuAiDifficulty;
  onAiDifficultyChange: (d: GomokuAiDifficulty) => void;
  onTurnChange: (t: "user" | "bot") => void;
  onBoardRestart: () => void;
  appendGomokuGameAssistantText: (content: string) => void;
  /** Latest grid + clock for position analysis (LLM / side-chat). */
  onBoardSnapshot?: (snapshot: GomokuBoardSnapshot) => void;
};

export function GomokuBoard({
  matchKey,
  tr,
  onQuit,
  onHideBoard,
  aiMoveOptions,
  gameReplyStyle,
  aiDifficulty,
  onAiDifficultyChange,
  onTurnChange,
  onBoardRestart,
  appendGomokuGameAssistantText,
  onBoardSnapshot,
}: GomokuBoardProps) {
  const [board, setBoard] = useState<Cell[]>(emptyBoard);
  const [turn, setTurn] = useState<Turn>("black");
  const [result, setResult] = useState<MatchResult>(null);
  const lastPlacementRef = useRef<{ x: number; y: number; by: Side } | null>(null);

  const boardIsEmpty = useMemo(() => board.every((x) => x === EMPTY), [board]);
  const canChangeDifficulty = boardIsEmpty;

  const resetLocalBoard = useCallback(() => {
    lastPlacementRef.current = null;
    setBoard(emptyBoard());
    setTurn("black");
    setResult(null);
  }, []);

  useEffect(() => {
    resetLocalBoard();
  }, [matchKey, resetLocalBoard]);

  const restart = useCallback(() => {
    // If the bot has an unavoidable 2-move win from this position, add a small in-character remark.
    // This is a heuristic check intended for flavor; it shouldn't block restart even if it fails.
    if (result == null && !boardIsEmpty && turn === "black") {
      try {
        const inevitable = isAttackerWinInTwoInevitableFromDefenderTurn(board, WHITE, BLACK, {
          rng: Math.random,
        });
        if (inevitable) {
          appendGomokuGameAssistantText(
            pickGomokuRestartTauntWinInTwo(gameReplyStyle, tr, Math.random)
          );
        }
      } catch {
        // ignore
      }
    }
    onBoardRestart();
    resetLocalBoard();
  }, [
    result,
    boardIsEmpty,
    turn,
    board,
    gameReplyStyle,
    tr,
    appendGomokuGameAssistantText,
    onBoardRestart,
    resetLocalBoard,
  ]);

  const statusText = (() => {
    if (result === "black_win") return tr("games.gomokuYouWin");
    if (result === "white_win") return tr("games.gomokuOpponentWin");
    if (result === "draw") return tr("games.gomokuDraw");
    return turn === "black" ? tr("games.gomokuYourTurn") : tr("games.gomokuOpponentTurn");
  })();

  const onCellClick = useCallback(
    (row: number, col: number) => {
      if (result != null || turn !== "black") return;
      const played = tryPlay(board, row, col, BLACK);
      if (!played) return;
      lastPlacementRef.current = { x: col, y: row, by: "user" };
      setBoard(played.board);
      const end = terminalFromOutcome(played.outcome);
      if (end != null) {
        setResult(end);
        return;
      }
      onTurnChange("bot");
      setTurn("white");
    },
    [board, result, turn, onTurnChange]
  );

  useEffect(() => {
    if (result != null || turn !== "white") return;
    const id = window.setTimeout(() => {
      setBoard((prev) => {
        const move =
          chooseMoveByDifficulty(prev, WHITE, BLACK, aiDifficulty, {
            rng: Math.random,
            ...aiMoveOptions,
          }) ?? randomEmptyCell(prev, Math.random);
        if (!move) {
          queueMicrotask(() => setResult("draw"));
          return prev;
        }
        const played = tryPlay(prev, move.row, move.col, WHITE);
        if (!played) return prev;
        lastPlacementRef.current = { x: move.col, y: move.row, by: "bot" };
        const end = terminalFromOutcome(played.outcome);
        if (end != null) {
          queueMicrotask(() => setResult(end));
        } else {
          queueMicrotask(() => {
            onTurnChange("user");
            setTurn("black");
          });
        }
        return played.board;
      });
    }, 420);
    return () => window.clearTimeout(id);
  }, [turn, result, aiMoveOptions, aiDifficulty, onTurnChange]);

  useEffect(() => {
    if (!onBoardSnapshot) return;
    const last = lastPlacementRef.current;
    const next_to_move: Side = turn === "black" ? "user" : "bot";
    const match_result: GomokuMatchResult | null =
      result === null ? null : result === "black_win" ? "user_win" : result === "white_win" ? "bot_win" : "draw";
    onBoardSnapshot({
      board: board.slice(),
      last_move: last ? { x: last.x, y: last.y } : null,
      last_move_by: last ? last.by : null,
      next_to_move,
      game_over: result !== null,
      match_result,
    });
  }, [board, turn, result, onBoardSnapshot]);

  return (
    <div className="gomoku-game-board-col" aria-label={tr("games.gomokuBoardAria")}>
      <div className="gomoku-board-card">
        <div className="gomoku-board-toolbar gomoku-board-toolbar--game-card">
          <div className="gomoku-board-toolbar-main">
            <span className="gomoku-board-label">{tr("games.gomoku")}</span>
            <span className="gomoku-board-status">{statusText}</span>
          </div>
          <div
            className="gomoku-difficulty"
            role="group"
            aria-label={tr("games.gomokuDifficultyGroupAria")}
            title={canChangeDifficulty ? undefined : tr("games.gomokuDifficultyLockedHint")}
          >
            <span className="gomoku-difficulty-label">{tr("games.gomokuDifficulty")}</span>
            <div className="gomoku-difficulty-toggle">
              <button
                type="button"
                className={`gomoku-difficulty-btn${aiDifficulty === "relaxed" ? " gomoku-difficulty-btn--active" : ""}`}
                disabled={!canChangeDifficulty}
                aria-pressed={aiDifficulty === "relaxed"}
                title={canChangeDifficulty ? tr("games.gomokuDifficultyRelaxed") : tr("games.gomokuDifficultyLockedHint")}
                onClick={() => onAiDifficultyChange("relaxed")}
              >
                {tr("games.gomokuDifficultyRelaxed")}
              </button>
              <button
                type="button"
                className={`gomoku-difficulty-btn${aiDifficulty === "serious" ? " gomoku-difficulty-btn--active" : ""}`}
                disabled={!canChangeDifficulty}
                aria-pressed={aiDifficulty === "serious"}
                title={canChangeDifficulty ? tr("games.gomokuDifficultySerious") : tr("games.gomokuDifficultyLockedHint")}
                onClick={() => onAiDifficultyChange("serious")}
              >
                {tr("games.gomokuDifficultySerious")}
              </button>
            </div>
          </div>
          <div className="gomoku-board-actions">
            <button
              type="button"
              className="gomoku-action-btn"
              onClick={restart}
              title={tr("games.gomokuRestartHint")}
            >
              {tr("games.gomokuRestart")}
            </button>
            <button type="button" className="gomoku-action-btn gomoku-action-btn--danger" onClick={onQuit} title={tr("games.gomokuQuitHint")}>
              {tr("games.gomokuQuit")}
            </button>
            <button
              type="button"
              className="gomoku-action-btn gomoku-action-btn--secondary"
              onClick={onHideBoard}
              title={tr("games.gomokuHideHint")}
              aria-label={tr("games.gomokuCloseBoard")}
            >
              {tr("games.gomokuHide")}
            </button>
          </div>
        </div>
        <div className="gomoku-grid" role="grid" aria-colcount={GOMOKU_SIZE} aria-rowcount={GOMOKU_SIZE}>
          {Array.from({ length: GOMOKU_CELL_COUNT }, (_, i) => {
            const row = Math.floor(i / GOMOKU_SIZE);
            const col = i % GOMOKU_SIZE;
            const stone = board[i];
            const playable = result == null && turn === "black" && stone === EMPTY;
            const ariaRow = row + 1;
            const ariaCol = col + 1;
            return (
              <button
                key={i}
                type="button"
                className={[
                  "gomoku-cell",
                  stone === BLACK ? "gomoku-cell--black" : "",
                  stone === WHITE ? "gomoku-cell--white" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                aria-label={tr("games.gomokuCellAria").replace("{row}", String(ariaRow)).replace("{col}", String(ariaCol))}
                disabled={!playable}
                onClick={() => onCellClick(row, col)}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
