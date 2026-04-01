"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type FormEvent,
  type ReactNode,
  type RefObject,
  type SetStateAction,
} from "react";
import type { Bot, Message, Relationship } from "@/lib/api";
import type { Locale } from "@/lib/translations";
import { GomokuBoard } from "@/components/GomokuBoard";
import {
  analyzePosition,
  decideGomokuDialogue,
  gomokuPersonaReply,
  pickGomokuPolicyLine,
  EMPTY,
  type ActiveGomokuGame,
  type GomokuAiDifficulty,
  type GomokuBoardSnapshot,
  type GomokuDialogueReason,
  type GomokuPositionSummary,
  type GomokuReactionType,
} from "@/lib/gomoku";
import { moodTooltip } from "@/lib/moodTooltips";
import { normalizeGameReplyStyle } from "@/lib/botGameReplyStyle";
import { GamesMenu } from "@/components/Games";

export function useGomokuGameSession(opts: {
  token: string | null;
  selectedBotId: number | "add-bot";
  sidebarView: "chat" | "add-bot";
  customBots: Bot[];
  messages: Message[];
  setMessages: Dispatch<SetStateAction<Message[]>>;
  tr: (key: string) => string;
  sortMessagesByOrder: (m: Message[]) => Message[];
}) {
  const { token, selectedBotId, sidebarView, customBots, messages, setMessages, tr, sortMessagesByOrder } = opts;
  const [gomokuModalOpen, setGomokuModalOpen] = useState(false);
  const [gomokuBoardOpen, setGomokuBoardOpen] = useState(false);
  const [gomokuSessionSinceMs, setGomokuSessionSinceMs] = useState<number | null>(null);
  const [gomokuAiDifficulty, setGomokuAiDifficulty] = useState<GomokuAiDifficulty>("serious");
  const [activeGame, setActiveGame] = useState<ActiveGomokuGame | null>(null);
  const [gomokuGameChat, setGomokuGameChat] = useState<Message[]>([]);
  const [gomokuPositionSummary, setGomokuPositionSummary] = useState<GomokuPositionSummary | null>(null);
  const prevGomokuSummaryRef = useRef<GomokuPositionSummary | null>(null);
  const policySpokenFingerprintRef = useRef<string | null>(null);
  const lastSpokenDecisionRef = useRef<{
    reaction: GomokuReactionType;
    reason: GomokuDialogueReason;
    move_count: number;
  } | null>(null);

  const handleStartGomoku = useCallback(() => {
    setGomokuModalOpen(false);
    prevGomokuSummaryRef.current = null;
    setGomokuPositionSummary(null);
    policySpokenFingerprintRef.current = null;
    lastSpokenDecisionRef.current = null;
    if (!token || selectedBotId === "add-bot") return;
    const bot = customBots.find((b) => b.id === selectedBotId);
    if (!bot) return;
    const botDisplayName = bot.name?.trim() || tr("chat.roleAssistant");
    const now = Date.now();
    const systemMsg: Message = {
      id: -now,
      user_id: 0,
      session_id: 0,
      role: "system",
      content: tr("games.gomokuStarted").replaceAll("{name}", botDisplayName),
      created_at: new Date(now).toISOString(),
    };
    const assistantMsg: Message = {
      id: -(now + 1),
      user_id: 0,
      session_id: 0,
      role: "assistant",
      content: gomokuPersonaReply(tr, bot),
      created_at: new Date(now + 1).toISOString(),
    };
    // Keep minigame auto/system lines out of the main transcript (no DB write).
    // Only user-initiated side-chat messages (and bot replies to them) are persisted.
    setGomokuGameChat([systemMsg, assistantMsg]);
    setGomokuSessionSinceMs(now);
    setGomokuBoardOpen(true);
    setActiveGame({
      type: "gomoku",
      difficulty: gomokuAiDifficulty,
      current_turn: "user",
      bot_side: "white",
    });
  }, [token, selectedBotId, customBots, tr, gomokuAiDifficulty]);

  const handleGomokuQuit = useCallback(() => {
    setGomokuBoardOpen(false);
    setGomokuSessionSinceMs(null);
    setActiveGame(null);
    setGomokuGameChat([]);
    prevGomokuSummaryRef.current = null;
    setGomokuPositionSummary(null);
    policySpokenFingerprintRef.current = null;
    lastSpokenDecisionRef.current = null;
  }, []);

  const syncGomokuDifficulty = useCallback((d: GomokuAiDifficulty) => {
    setGomokuAiDifficulty(d);
    setActiveGame((prev) => (prev ? { ...prev, difficulty: d } : prev));
  }, []);

  const setGomokuTurn = useCallback((t: "user" | "bot") => {
    setActiveGame((prev) => (prev ? { ...prev, current_turn: t } : prev));
  }, []);

  const resetGomokuBoardSession = useCallback(() => {
    policySpokenFingerprintRef.current = null;
    lastSpokenDecisionRef.current = null;
    setActiveGame((prev) => (prev ? { ...prev, current_turn: "user" } : prev));
  }, []);

  const appendGomokuGameAssistantText = useCallback(
    (content: string) => {
      const now = Date.now();
      const assistantMsg: Message = {
        id: -(now + 2),
        user_id: 0,
        session_id: 0,
        role: "assistant",
        content,
        created_at: new Date(now).toISOString(),
      };
      setGomokuGameChat((prev) => sortMessagesByOrder([...prev, assistantMsg]));
    },
    [sortMessagesByOrder],
  );

  const handleGomokuBoardSnapshot = useCallback(
    (s: GomokuBoardSnapshot) => {
      const moveCount = s.board.filter((c) => c !== EMPTY).length;
      if (moveCount === 0) {
        prevGomokuSummaryRef.current = null;
      }
      const summary = analyzePosition({
        board: s.board,
        current_turn: s.next_to_move,
        last_move: s.last_move,
        last_move_by: s.last_move_by,
        user_stone: "black",
        bot_stone: "white",
        game_over: s.game_over,
        match_result: s.match_result,
        prev_summary: prevGomokuSummaryRef.current,
      });
      prevGomokuSummaryRef.current = summary;
      setGomokuPositionSummary(summary);

      const bot = customBots.find((b) => b.id === selectedBotId);
      const style = normalizeGameReplyStyle(bot?.personality);
      const decision = decideGomokuDialogue({
        summary,
        style,
        game_over: s.game_over,
      });
      const line = pickGomokuPolicyLine(decision, tr, Math.random);
      if (!line) return;

      // Cooldown / suppression: avoid repeating the same kind of line every move.
      // Only allow terminal results through; even "can finish" can happen repeatedly and should be throttled.
      const last = lastSpokenDecisionRef.current;
      const isCritical =
        decision.reason === "bot_win" ||
        decision.reason === "user_win" ||
        decision.reaction === "endgame_result";
      if (!isCritical && last) {
        const delta = moveCount - last.move_count;
        const sameKind = decision.reaction === last.reaction && decision.reason === last.reason;
        if (sameKind && delta <= 6) return;
        if (delta < 6) return; // global rate limit: at most one line per ~6 plies
        if (decision.reaction === "react_to_threat" && last.reaction === "react_to_threat" && delta <= 6) return;
      }

      const fp =
        decision.reaction === "endgame_result"
          ? `policy:end:${summary.match_result ?? ""}`
          : `policy:${decision.reaction}:${decision.reason}:${moveCount}:${summary.events.slice().sort().join("|")}`;
      if (policySpokenFingerprintRef.current === fp) return;
      policySpokenFingerprintRef.current = fp;

      if (decision.reaction) {
        lastSpokenDecisionRef.current = {
          reaction: decision.reaction,
          reason: decision.reason,
          move_count: moveCount,
        };
      }
      appendGomokuGameAssistantText(line);
    },
    [appendGomokuGameAssistantText, customBots, selectedBotId, tr],
  );

  useEffect(() => {
    setGomokuBoardOpen(false);
    setGomokuSessionSinceMs(null);
    setActiveGame(null);
    setGomokuGameChat([]);
    prevGomokuSummaryRef.current = null;
    setGomokuPositionSummary(null);
    policySpokenFingerprintRef.current = null;
    lastSpokenDecisionRef.current = null;
  }, [selectedBotId, sidebarView]);

  const gomokuThreadMessages = useMemo(() => {
    if (gomokuSessionSinceMs == null) return [];
    // Render only the minigame thread here. Game side-chat is persisted to the main transcript
    // separately; mixing `messages` back in would duplicate bubbles.
    return sortMessagesByOrder([...gomokuGameChat]).slice(-30);
  }, [gomokuSessionSinceMs, gomokuGameChat, sortMessagesByOrder]);

  return {
    gomokuModalOpen,
    setGomokuModalOpen,
    gomokuBoardOpen,
    setGomokuBoardOpen,
    gomokuSessionSinceMs,
    handleStartGomoku,
    handleGomokuQuit,
    gomokuCompanionMessages: gomokuThreadMessages,
    activeGame,
    gomokuGameChat,
    setGomokuGameChat,
    gomokuAiDifficulty,
    syncGomokuDifficulty,
    setGomokuTurn,
    resetGomokuBoardSession,
    appendGomokuGameAssistantText,
    gomokuPositionSummary,
    handleGomokuBoardSnapshot,
  };
}

export type GomokuGameStartModalProps = {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  botDisplayName: string;
  tr: (key: string) => string;
};

export function GomokuGameStartModal({ open, onClose, onConfirm, botDisplayName, tr }: GomokuGameStartModalProps) {
  if (!open) return null;
  return (
    <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="gomoku-game-title" onClick={onClose}>
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <h2 id="gomoku-game-title" className="modal-title">
          {tr("games.gomokuModalTitle")}
        </h2>
        <p className="modal-body">{tr("games.gomokuModalBody").replaceAll("{name}", botDisplayName)}</p>
        <div className="modal-actions">
          <button type="button" className="modal-btn modal-btn-cancel" onClick={onClose}>
            {tr("common.cancel")}
          </button>
          <button type="button" className="modal-btn" onClick={onConfirm}>
            {tr("games.play")}
          </button>
        </div>
      </div>
    </div>
  );
}

export type GomokuGameResumeBarProps = {
  tr: (key: string) => string;
  onShowBoard: () => void;
};

export function GomokuGameResumeBar({ tr, onShowBoard }: GomokuGameResumeBarProps) {
  return (
    <div className="gomoku-resume-bar" role="region" aria-label={tr("games.gomoku")}>
      <span className="gomoku-resume-bar-hint">{tr("games.gomokuResumeBarHint")}</span>
      <button type="button" className="gomoku-resume-bar-btn" onClick={onShowBoard}>
        {tr("games.gomokuShowBoard")}
      </button>
    </div>
  );
}

type StatExplain = "trust" | "resonance" | null;

function GomokuGameCompanionStatusBar({
  tr,
  locale,
  relationship,
  statExplainRootRef,
  statExplainOpen,
  setStatExplainOpen,
  trustFlash,
  resonanceFlash,
  trustTierDescription,
  resonanceTierDescription,
}: {
  tr: (key: string) => string;
  locale: Locale;
  relationship: Relationship;
  statExplainRootRef: RefObject<HTMLDivElement>;
  statExplainOpen: StatExplain;
  setStatExplainOpen: Dispatch<SetStateAction<StatExplain>>;
  trustFlash: "up" | "down" | null;
  resonanceFlash: "up" | "down" | null;
  trustTierDescription: (trust: number) => string;
  resonanceTierDescription: (resonance: number) => string;
}) {
  return (
    <div className="status-bar status-bar--gomoku-companion" ref={statExplainRootRef} role="status" aria-live="polite">
      <div className="stat-chip-wrap">
        <button
          type="button"
          className={`stat-chip ${statExplainOpen === "trust" ? "stat-chip-active" : ""}`}
          aria-expanded={statExplainOpen === "trust"}
          aria-controls="stat-popover-trust"
          id="stat-trigger-trust"
          onClick={() => setStatExplainOpen((o) => (o === "trust" ? null : "trust"))}
        >
          {tr("stats.trust")}{" "}
          <span
            className={`stat-chip-value${trustFlash === "up" ? " stat-chip-value-flash-up" : ""}${trustFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
          >
            {relationship.trust}
          </span>
        </button>
        {statExplainOpen === "trust" && (
          <div id="stat-popover-trust" className="stat-popover" role="dialog" aria-labelledby="stat-trigger-trust">
            <div className="stat-popover-accent" aria-hidden />
            <div className="stat-popover-head">
              <span className="stat-popover-label">{tr("stats.trust")}</span>
              <span
                className={`stat-popover-num${trustFlash === "up" ? " stat-chip-value-flash-up" : ""}${trustFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
              >
                {relationship.trust}
              </span>
            </div>
            <p className="stat-popover-text">{trustTierDescription(relationship.trust)}</p>
          </div>
        )}
      </div>
      <span className="status-sep" aria-hidden>
        ·
      </span>
      <div className="stat-chip-wrap">
        <button
          type="button"
          className={`stat-chip ${statExplainOpen === "resonance" ? "stat-chip-active" : ""}`}
          aria-expanded={statExplainOpen === "resonance"}
          aria-controls="stat-popover-resonance"
          id="stat-trigger-resonance"
          onClick={() => setStatExplainOpen((o) => (o === "resonance" ? null : "resonance"))}
        >
          {tr("stats.resonance")}{" "}
          <span
            className={`stat-chip-value${resonanceFlash === "up" ? " stat-chip-value-flash-up" : ""}${resonanceFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
          >
            {relationship.resonance}
          </span>
        </button>
        {statExplainOpen === "resonance" && (
          <div id="stat-popover-resonance" className="stat-popover" role="dialog" aria-labelledby="stat-trigger-resonance">
            <div className="stat-popover-accent stat-popover-accent-resonance" aria-hidden />
            <div className="stat-popover-head">
              <span className="stat-popover-label">{tr("stats.resonance")}</span>
              <span
                className={`stat-popover-num${resonanceFlash === "up" ? " stat-chip-value-flash-up" : ""}${resonanceFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
              >
                {relationship.resonance}
              </span>
            </div>
            <p className="stat-popover-text">{resonanceTierDescription(relationship.resonance)}</p>
          </div>
        )}
      </div>
      <span className="status-sep" aria-hidden>
        ·
      </span>
      <span
        className="mood-with-tooltip mood-tooltip-host"
        tabIndex={0}
        aria-label={tr("stats.moodAria").replace("{mood}", relationship.mood)}
      >
        <span className={`mood-dot mood-${relationship.mood}`} aria-hidden />
        <span className="mood-label">{relationship.mood}</span>
        <span className="bot-profile-tooltip mood-tooltip-popover" role="tooltip">
          {moodTooltip(relationship.mood, locale)}
        </span>
      </span>
    </div>
  );
}

export type GomokuGamePlayingViewProps = {
  tr: (key: string) => string;
  locale: Locale;
  matchKey: number;
  onQuit: () => void;
  onHideBoard: () => void;
  onRequestGomokuModal: () => void;
  customBots: Bot[];
  selectedBotId: number;
  setBotProfileOpen: (open: boolean) => void;
  botProfileOpen: boolean;
  relationship: Relationship | null;
  statExplainRootRef: RefObject<HTMLDivElement>;
  statExplainOpen: StatExplain;
  setStatExplainOpen: Dispatch<SetStateAction<StatExplain>>;
  trustFlash: "up" | "down" | null;
  resonanceFlash: "up" | "down" | null;
  trustTierDescription: (trust: number) => string;
  resonanceTierDescription: (resonance: number) => string;
  messagesRef: RefObject<HTMLDivElement>;
  companionMessages: Message[];
  mapMessageList: (msgs: Message[]) => ReactNode;
  botTyping: boolean;
  handleSend: (e: FormEvent<HTMLFormElement>) => void;
  input: string;
  setInput: (v: string) => void;
  loading: boolean;
  sendInputRef: RefObject<HTMLTextAreaElement>;
  error: string;
  gomokuAiDifficulty: GomokuAiDifficulty;
  onGomokuAiDifficultyChange: (d: GomokuAiDifficulty) => void;
  onGomokuTurnChange: (t: "user" | "bot") => void;
  onGomokuBoardRestart: () => void;
  appendGomokuGameAssistantText: (content: string) => void;
  onGomokuBoardSnapshot: (snapshot: GomokuBoardSnapshot) => void;
};

/** Full-width Gomoku game layout: board + side chat (status, messages, composer). */
export function GomokuGamePlayingView({
  tr,
  locale,
  matchKey,
  onQuit,
  onHideBoard,
  onRequestGomokuModal,
  customBots,
  selectedBotId,
  setBotProfileOpen,
  botProfileOpen,
  relationship,
  statExplainRootRef,
  statExplainOpen,
  setStatExplainOpen,
  trustFlash,
  resonanceFlash,
  trustTierDescription,
  resonanceTierDescription,
  messagesRef,
  companionMessages,
  mapMessageList,
  botTyping,
  handleSend,
  input,
  setInput,
  loading,
  sendInputRef,
  error,
  gomokuAiDifficulty,
  onGomokuAiDifficultyChange,
  onGomokuTurnChange,
  onGomokuBoardRestart,
  appendGomokuGameAssistantText,
  onGomokuBoardSnapshot,
}: GomokuGamePlayingViewProps) {
  const profileBot = customBots.find((b) => b.id === selectedBotId);
  const gameReplyStyle = normalizeGameReplyStyle(profileBot?.personality);
  const assistantName = profileBot?.name?.trim() || tr("chat.roleAssistant");
  const assistantAvatar = profileBot?.avatar_data_url ?? "/avatar-assistant.png";
  const shouldAutoScrollRef = useRef(true);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    if (!shouldAutoScrollRef.current) return;
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [companionMessages, botTyping, messagesRef]);

  return (
    <div className="wrap chat-wrap chat-wrap--with-gomoku">
      <div className="gomoku-game-container">
        <GomokuBoard
          matchKey={matchKey}
          tr={tr}
          onQuit={onQuit}
          onHideBoard={onHideBoard}
          gameReplyStyle={gameReplyStyle}
          aiDifficulty={gomokuAiDifficulty}
          onAiDifficultyChange={onGomokuAiDifficultyChange}
          onTurnChange={onGomokuTurnChange}
          onBoardRestart={onGomokuBoardRestart}
          appendGomokuGameAssistantText={appendGomokuGameAssistantText}
          onBoardSnapshot={onGomokuBoardSnapshot}
        />
        <aside className="gomoku-game-companion" aria-label={tr("games.gomokuCompanionAria")}>
          <header className="gomoku-companion-header">
            <button
              type="button"
              className="chat-header-bot-trigger gomoku-companion-bot-trigger"
              onClick={() => profileBot && setBotProfileOpen(true)}
              aria-expanded={botProfileOpen}
              aria-haspopup="dialog"
              disabled={!profileBot}
            >
              <span className="chat-header-bot-avatar" aria-hidden>
                {profileBot?.avatar_data_url ? (
                  <img src={profileBot.avatar_data_url} alt="" className="avatar-img" />
                ) : (
                  <span className="chat-header-bot-avatar-fallback">{(profileBot?.name?.trim()?.[0] ?? "?").toUpperCase()}</span>
                )}
              </span>
              <span className="chat-header-bot-name">{profileBot?.name ?? tr("chat.fallbackTitle")}</span>
            </button>
            {relationship && (
              <GomokuGameCompanionStatusBar
                tr={tr}
                locale={locale}
                relationship={relationship}
                statExplainRootRef={statExplainRootRef}
                statExplainOpen={statExplainOpen}
                setStatExplainOpen={setStatExplainOpen}
                trustFlash={trustFlash}
                resonanceFlash={resonanceFlash}
                trustTierDescription={trustTierDescription}
                resonanceTierDescription={resonanceTierDescription}
              />
            )}
          </header>
          <div
            className="messages messages--gomoku-companion"
            ref={messagesRef}
            onScroll={() => {
              const el = messagesRef.current;
              if (!el) return;
              const remaining = el.scrollHeight - el.scrollTop - el.clientHeight;
              // If the user scrolls up to read history, don't yank them back down.
              shouldAutoScrollRef.current = remaining < 48;
            }}
          >
            {companionMessages.length === 0 && <p className="muted gomoku-companion-empty">{tr("games.gomokuCompanionEmpty")}</p>}
            {mapMessageList(companionMessages)}
            {botTyping && (
              <div className="msg-row msg-row-assistant" aria-live="polite" aria-label={tr("chat.typing").replace("{name}", assistantName)}>
                <div className="msg-avatar msg-avatar-assistant msg-avatar-img" aria-hidden>
                  <img src={assistantAvatar} alt="" className="avatar-img" />
                </div>
                <div className="msg msg-assistant">
                  <span className="role">{assistantName}</span>
                  <span className="typing-dots" aria-hidden="true">
                    <span className="dot" />
                    <span className="dot" />
                    <span className="dot" />
                  </span>
                  <span className="sr-only">{tr("chat.thinking")}</span>
                </div>
              </div>
            )}
          </div>
          <form onSubmit={handleSend} className="send-form send-form--gomoku-compact">
            <div className="gomoku-input-shell">
              <textarea
                ref={sendInputRef}
                placeholder={tr("chat.typeMessage")}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    (e.currentTarget as HTMLTextAreaElement).form?.requestSubmit();
                  }
                }}
                disabled={loading}
                rows={2}
                className="send-input send-input--gomoku-compact"
              />
              <div className="gomoku-input-shell-row">
                <GamesMenu variant="gomoku" tr={tr} onPickGomoku={onRequestGomokuModal} />
                <div className="send-form-send-slot">
                  <button
                    type="submit"
                    className="send-btn-icon send-btn-icon--gomoku-compact"
                    disabled={loading || !input.trim()}
                    aria-label={tr("chat.send")}
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                      <path d="M22 2L11 13" />
                      <path d="M22 2L15 22L11 13L2 9L22 2Z" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>
          </form>
          {error && <p className="error gomoku-companion-error">{error}</p>}
        </aside>
      </div>
    </div>
  );
}
