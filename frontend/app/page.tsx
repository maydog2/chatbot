"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { api, type Message, type Relationship, type Bot } from "@/lib/api";
import {
  DEFAULT_PRIMARY_INTEREST_KEY,
  PRIMARY_INTEREST_OPTIONS,
  SECONDARY_INTEREST_OPTIONS,
} from "@/lib/botInterests";
import {
  DEFAULT_GAME_REPLY_STYLE,
  GAME_REPLY_STYLE_OPTIONS,
  normalizeGameReplyStyle,
  type GameReplyStyle,
} from "@/lib/botGameReplyStyle";
import { INITIATIVE_OPTIONS, type InitiativeLevel, normalizeInitiativeLevel } from "@/lib/botInitiative";
import { generateCurrentStyleSummary } from "@/lib/currentStyleSummary";
import { useLocale } from "@/lib/locale";
import { GamesMenu } from "@/components/Games";
import {
  GomokuGamePlayingView,
  GomokuGameResumeBar,
  GomokuGameStartModal,
  useGomokuGameSession,
} from "@/components/GomokuGame";
import { moodTooltip } from "@/lib/moodTooltips";

const TOKEN_KEY = "chatbot_token";


const MAX_BOTS = 10;

/** Remember Me: Reads the token from localStorage or sessionStorage (if a user has logged in previously on the same machine and browser, re-authentication is not required). */
function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY);
}

/** Write Token: If `rememberMe` is true, use `localStorage` (persists even after closing the browser); otherwise, use `sessionStorage` (expires when the tab is closed). */
function setStoredToken(t: string, rememberMe: boolean): void {
  if (rememberMe) {
    localStorage.setItem(TOKEN_KEY, t);
    sessionStorage.removeItem(TOKEN_KEY);
  } else {
    sessionStorage.setItem(TOKEN_KEY, t);
    localStorage.removeItem(TOKEN_KEY);
  }
}

function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

function roleSortRank(role: string): number {
  if (role === "system") return 0;
  if (role === "user") return 1;
  if (role === "assistant") return 2;
  return 3;
}

/** Sort messages by created_at ascending; ties: system → user → assistant, then by id. */
function sortMessagesByOrder(msgs: Message[]): Message[] {
  return [...msgs].sort((a, b) => {
    const tA = new Date(a.created_at).getTime();
    const tB = new Date(b.created_at).getTime();
    const validA = Number.isFinite(tA);
    const validB = Number.isFinite(tB);
    if (validA && validB && tA !== tB) return tA - tB;
    if (validA !== validB) return validA ? -1 : 1;
    if (validA && validB) {
      const rankDiff = roleSortRank(a.role) - roleSortRank(b.role);
      if (rankDiff !== 0) return rankDiff;
      const roleOrder = a.role === "user" && b.role === "assistant" ? -1 : a.role === "assistant" && b.role === "user" ? 1 : 0;
      if (roleOrder !== 0) return roleOrder;
    }
    return (a.id ?? 0) - (b.id ?? 0);
  });
}

/** Trust 0–100 tier copy (hover on status bar). */
function trustTierDescription(trust: number, tr: (k: string) => string): string {
  const x = Math.max(0, Math.min(100, Math.floor(trust)));
  if (x <= 19) return tr("trust.0");
  if (x <= 39) return tr("trust.1");
  if (x <= 59) return tr("trust.2");
  if (x <= 79) return tr("trust.3");
  return tr("trust.4");
}

/** Resonance 0–100 tier copy (hover on status bar). */
function resonanceTierDescription(resonance: number, tr: (k: string) => string): string {
  const r = Math.max(0, Math.min(100, Math.floor(resonance)));
  if (r <= 19) return tr("resonance.0");
  if (r <= 39) return tr("resonance.1");
  if (r <= 59) return tr("resonance.2");
  if (r <= 79) return tr("resonance.3");
  return tr("resonance.4");
}

// Only allow letters, digits, underscore, hyphen, period for username (no Chinese/emoji)
const filterUsername = (s: string) => s.replace(/[^a-zA-Z0-9_.-]/g, "");
// Only allow printable ASCII for password (letters, numbers, common symbols; no Chinese/emoji)
const filterPassword = (s: string) => s.replace(/[^\x20-\x7E]/g, "");

export default function Home() {
  const { t: tr, locale, setLocale } = useLocale();
  const [mounted, setMounted] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [relationship, setRelationship] = useState<Relationship | null>(null);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [botTyping, setBotTyping] = useState(false);
  const [me, setMe] = useState<{ display_name: string; avatar_data_url: string | null } | null>(null);
  const [authTab, setAuthTab] = useState<"login" | "register">("login");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [sidebarView, setSidebarView] = useState<"chat" | "add-bot">("add-bot");
  const [selectedBotId, setSelectedBotId] = useState<number | "add-bot">("add-bot");
  const [customBots, setCustomBots] = useState<Bot[]>([]);
  const [menuOpenBotId, setMenuOpenBotId] = useState<number | null>(null);
  const [deleteConfirmBot, setDeleteConfirmBot] = useState<{ id: number; name: string } | null>(null);
  const [editBotModal, setEditBotModal] = useState<
    | null
    | { mode: "rename"; id: number; initialName: string; value: string }
    | { mode: "persona"; id: number; initialDirection: string; value: string }
    | { mode: "formOfAddress"; id: number; initialFormOfAddress: string; value: string }
  >(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [editMeModal, setEditMeModal] = useState<null | { mode: "rename"; value: string }>(null);
  const [avatarModal, setAvatarModal] = useState<
    | null
    | { target: "user"; dataUrl: string | null; dragging: boolean; error: string }
    | { target: "bot"; botId: number; botName: string; dataUrl: string | null; dragging: boolean; error: string }
  >(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false);
  /** Latest relationship for comparing metrics after send (avoids stale closure). */
  const relationshipRef = useRef<Relationship | null>(null);
  const statFlashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const userMenuRef = useRef<HTMLDivElement>(null);
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const sendInputRef = useRef<HTMLTextAreaElement>(null);
  const statExplainRootRef = useRef<HTMLDivElement>(null);
  // Sticky minigame relationship events: applied once on next gomoku side-chat send.
  const gomokuRestartedWhileLosingRef = useRef(false);
  const gomokuImmediateAppliedRef = useRef<Set<string>>(new Set());
  const gomokuImmediateMatchKeyRef = useRef<number | null>(null);
  const [statExplainOpen, setStatExplainOpen] = useState<null | "trust" | "resonance">(null);
  /** Brief highlight on Trust / Resonance when values change after a reply. */
  const [trustFlash, setTrustFlash] = useState<"up" | "down" | null>(null);
  const [resonanceFlash, setResonanceFlash] = useState<"up" | "down" | null>(null);
  const [connectionError, setConnectionError] = useState(false);
  const {
    gomokuModalOpen,
    setGomokuModalOpen,
    gomokuBoardOpen,
    setGomokuBoardOpen,
    gomokuSessionSinceMs,
    handleStartGomoku,
    handleGomokuQuit,
    gomokuCompanionMessages,
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
  } = useGomokuGameSession({
    token,
    selectedBotId,
    sidebarView,
    customBots,
    messages,
    setMessages,
    tr,
    sortMessagesByOrder,
  });

  const handleGomokuBoardRestart = useCallback(() => {
    const s = gomokuPositionSummary;
    // If the user restarts while behind, nudge relationship once (on next send).
    if (s && !s.game_over) {
      const losing =
        s.eval === "bot_winning" ||
        s.eval === "bot_slightly_ahead";
      if (losing) gomokuRestartedWhileLosingRef.current = true;
    }
    // Immediate feedback (no chat needed).
    if (token && selectedBotId !== "add-bot" && s && !s.game_over) {
      const losing =
        s.eval === "bot_winning" ||
        s.eval === "bot_slightly_ahead";
      if (losing) {
        const botId = selectedBotId as number;
        api
          .applyGomokuRelationshipEvents(token, botId, ["user_restarted_while_losing"], s)
          .then((rel) => {
            gomokuImmediateAppliedRef.current.add("user_restarted_while_losing");
            setRelationship((prev) => ({
              trust: rel.trust,
              resonance: rel.resonance,
              affection: rel.affection,
              openness: rel.openness,
              mood: rel.mood,
              display_name: rel.display_name || prev?.display_name || "",
            }));
          })
          .catch((err) => console.warn("applyGomokuRelationshipEvents restart failed", err));
      }
    }
    resetGomokuBoardSession();
  }, [gomokuPositionSummary, resetGomokuBoardSession]);

  // Immediate relationship feedback for Gomoku (no need to send a chat message).
  useEffect(() => {
    if (!token) return;
    if (!activeGame) return;
    if (selectedBotId === "add-bot") return;
    if (!gomokuPositionSummary) return;

    // Reset per match
    if (gomokuImmediateMatchKeyRef.current !== gomokuSessionSinceMs) {
      gomokuImmediateMatchKeyRef.current = gomokuSessionSinceMs ?? null;
      gomokuImmediateAppliedRef.current = new Set();
    }

    const s = gomokuPositionSummary;
    const events: string[] = [];
    if (s.events?.includes("user_created_threat")) events.push("user_created_strong_threat");
    if (s.events?.includes("user_blocked_bot_threat")) events.push("user_blocked_bot_threat");
    if (s.game_over) {
      if (s.match_result === "user_win") events.push("user_win");
      if (s.match_result === "bot_win") events.push("bot_win");
    }

    // Apply each event once per match
    const pending = events.filter((e) => !gomokuImmediateAppliedRef.current.has(e));
    if (pending.length === 0) return;

    const botId = selectedBotId as number;
    (async () => {
      try {
        const rel = await api.applyGomokuRelationshipEvents(token, botId, pending, s);
        pending.forEach((e) => gomokuImmediateAppliedRef.current.add(e));
        setRelationship((prev) => ({
          trust: rel.trust,
          resonance: rel.resonance,
          affection: rel.affection,
          openness: rel.openness,
          mood: rel.mood,
          display_name: rel.display_name || prev?.display_name || "",
        }));
      } catch (err) {
        // Non-fatal; the send message path will still apply on next side-chat.
        console.warn("applyGomokuRelationshipEvents failed", err);
      }
    })();
  }, [token, activeGame, selectedBotId, gomokuPositionSummary, gomokuSessionSinceMs]);
  const [botsLoaded, setBotsLoaded] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [botProfileOpen, setBotProfileOpen] = useState(false);
  const [botProfilePersonaEditing, setBotProfilePersonaEditing] = useState(false);
  const [botProfilePersonaDraft, setBotProfilePersonaDraft] = useState("");
  const [botProfilePersonaSaving, setBotProfilePersonaSaving] = useState(false);
  const [botProfileInterestsEditing, setBotProfileInterestsEditing] = useState(false);
  const [botProfilePrimaryDraft, setBotProfilePrimaryDraft] = useState<string>("");
  const [botProfileSecondaryDraft, setBotProfileSecondaryDraft] = useState<string[]>([]);
  const [botProfileInterestsSaving, setBotProfileInterestsSaving] = useState(false);
  const [botProfileInitiativeEditing, setBotProfileInitiativeEditing] = useState(false);
  const [botProfileInitiativeDraft, setBotProfileInitiativeDraft] = useState<InitiativeLevel>("medium");
  const [botProfileInitiativeSaving, setBotProfileInitiativeSaving] = useState(false);
  const [botProfileGameReplyEditing, setBotProfileGameReplyEditing] = useState(false);
  const [botProfileGameReplyDraft, setBotProfileGameReplyDraft] =
    useState<GameReplyStyle>(DEFAULT_GAME_REPLY_STYLE);
  const [botProfileGameReplySaving, setBotProfileGameReplySaving] = useState(false);
  const [botProfileNameEditing, setBotProfileNameEditing] = useState(false);
  const [botProfileNameDraft, setBotProfileNameDraft] = useState("");
  const [botProfileNameSaving, setBotProfileNameSaving] = useState(false);
  const [botProfileFoaEditing, setBotProfileFoaEditing] = useState(false);
  const [botProfileFoaDraft, setBotProfileFoaDraft] = useState("");
  const [botProfileFoaSaving, setBotProfileFoaSaving] = useState(false);
  const [authForm, setAuthForm] = useState({
    display_name: "",
    username: "",
    password: "",
  });

  const fetchMe = useCallback(async (t: string) => {
    try {
      const profile = await api.me(t);
      setMe(profile);
      return profile;
    } catch {
      setMe(null);
      return null;
    }
  }, []);

  const fetchBots = useCallback(async (t: string) => {
    try {
      const res = await api.listBots(t);
      setCustomBots(res.bots ?? []);
      return res.bots ?? [];
    } catch {
      setCustomBots([]);
      return [];
    }
  }, []);

  // Auto-grow send textarea by content: min 2 lines (send on 2nd line), max 10 lines
  useEffect(() => {
    const el = sendInputRef.current;
    if (!el) return;
    el.style.height = "auto";
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight) || 22;
    const minHeight = lineHeight * 2;
    const maxHeight = lineHeight * 10;
    el.style.height = `${Math.max(minHeight, Math.min(el.scrollHeight, maxHeight))}px`;
  }, [input]);

  useEffect(() => {
    if (!statExplainOpen) return;
    const onDown = (e: MouseEvent) => {
      if (statExplainRootRef.current?.contains(e.target as Node)) return;
      setStatExplainOpen(null);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setStatExplainOpen(null);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [statExplainOpen]);

  useEffect(() => {
    setStatExplainOpen(null);
    setBotProfileOpen(false);
  }, [selectedBotId]);

  useEffect(() => {
    if (!botProfileOpen) {
      setBotProfilePersonaEditing(false);
      setBotProfileInterestsEditing(false);
      setBotProfileInitiativeEditing(false);
      setBotProfileGameReplyEditing(false);
      setBotProfileNameEditing(false);
      setBotProfileFoaEditing(false);
      return;
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setBotProfileOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [botProfileOpen]);

  const saveBotPersonaFromProfile = async (botId: number) => {
    if (!token) return;
    setBotProfilePersonaSaving(true);
    setError("");
    try {
      const updated = await api.updateBot(token, botId, {
        direction: botProfilePersonaDraft.trim() || "",
      });
      setCustomBots((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      setBotProfilePersonaEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.saveDirection"));
    } finally {
      setBotProfilePersonaSaving(false);
    }
  };

  const saveBotInitiativeFromProfile = async (botId: number) => {
    if (!token) return;
    setBotProfileInitiativeSaving(true);
    setError("");
    try {
      const updated = await api.updateBot(token, botId, {
        initiative: botProfileInitiativeDraft,
      });
      setCustomBots((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      setBotProfileInitiativeEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.saveInitiative"));
    } finally {
      setBotProfileInitiativeSaving(false);
    }
  };

  const saveBotGameReplyFromProfile = async (botId: number, style: GameReplyStyle) => {
    if (!token) return;
    setBotProfileGameReplySaving(true);
    setError("");
    try {
      const updated = await api.updateBot(token, botId, {
        personality: style,
      });
      setCustomBots((prev) =>
        prev.map((x) =>
          x.id === updated.id
            ? { ...x, ...updated, personality: updated.personality ?? style }
            : x
        )
      );
      setBotProfileGameReplyEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.saveGameReplyStyle"));
    } finally {
      setBotProfileGameReplySaving(false);
    }
  };

  const saveBotInterestsFromProfile = async (botId: number) => {
    if (!token) return;
    setBotProfileInterestsSaving(true);
    setError("");
    try {
      const primaryKey =
        botProfilePrimaryDraft.trim() || DEFAULT_PRIMARY_INTEREST_KEY;
      const updated = await api.updateBot(token, botId, {
        primary_interest: primaryKey,
        secondary_interests: botProfileSecondaryDraft,
      });
      setCustomBots((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      setBotProfileInterestsEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.saveInterests"));
    } finally {
      setBotProfileInterestsSaving(false);
    }
  };

  const saveBotNameFromProfile = async (botId: number) => {
    if (!token) return;
    const next = botProfileNameDraft.trim();
    if (!next) {
      setError(tr("error.nameEmpty"));
      return;
    }
    setBotProfileNameSaving(true);
    setError("");
    try {
      const updated = await api.updateBot(token, botId, { name: next });
      setCustomBots((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      setBotProfileNameEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.saveName"));
    } finally {
      setBotProfileNameSaving(false);
    }
  };

  const saveBotFoaFromProfile = async (botId: number) => {
    if (!token) return;
    setBotProfileFoaSaving(true);
    setError("");
    try {
      const updated = await api.updateBot(token, botId, {
        form_of_address: botProfileFoaDraft.trim() || "",
      });
      setCustomBots((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      setBotProfileFoaEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.saveFoa"));
    } finally {
      setBotProfileFoaSaving(false);
    }
  };

  useEffect(() => {
    const t = getStoredToken();
    setToken(t);
    setMounted(true);
    if (t) {
      setConnectionError(false);
      setBotsLoaded(false);
      fetchMe(t).catch(() => {});
      const CONNECT_TIMEOUT_MS = 10000;
      const loadBots = Promise.race([
        fetchBots(t),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("Connection timeout")), CONNECT_TIMEOUT_MS)
        ),
      ]);
      loadBots
        .then((bots) => {
          setBotsLoaded(true);
          setConnectionError(false);
          if (bots.length > 0) {
            setSelectedBotId(bots[0].id);
            setSidebarView("chat");
            fetchRelationship(t, bots[0].id);
          } else {
            setSelectedBotId("add-bot");
            setSidebarView("add-bot");
          }
        })
        .catch(() => {
          setBotsLoaded(true);
          setConnectionError(true);
          setSelectedBotId("add-bot");
          setSidebarView("add-bot");
        });
    } else {
      setConnectionError(false);
      setBotsLoaded(true);
    }
  }, [fetchBots]);

  useEffect(() => {
    if (!token || sidebarView !== "chat" || selectedBotId === "add-bot") return;
    let cancelled = false;
    const botId = selectedBotId as number;
    (async () => {
      try {
        const res = await api.historyBot(token, botId);
        if (!cancelled) setMessages(sortMessagesByOrder(res.messages ?? []));
      } catch {
        if (!cancelled) setMessages([]);
      }
    })();
    return () => { cancelled = true; };
  }, [token, sidebarView, selectedBotId]);

  // Auto-scroll to newest message (and typing indicator).
  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;
    // Wait for DOM to paint before scrolling.
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
  }, [messages, botTyping, sidebarView, selectedBotId, gomokuBoardOpen]);

  useEffect(() => {
    if (!userMenuOpen) return;
    const onDocClick = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) setUserMenuOpen(false);
    };
    document.addEventListener("click", onDocClick, true);
    return () => document.removeEventListener("click", onDocClick, true);
  }, [userMenuOpen]);

  useEffect(() => {
    if (!menuOpenBotId) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpenBotId(null);
    };
    document.addEventListener("click", onDocClick, true);
    return () => document.removeEventListener("click", onDocClick, true);
  }, [menuOpenBotId]);

  const handleDeleteBot = (id: number, name: string) => {
    setMenuOpenBotId(null);
    setDeleteConfirmBot({ id, name });
  };

  const confirmDeleteBot = async () => {
    if (!deleteConfirmBot) return;
    const { id } = deleteConfirmBot;
    if (token) {
      try {
        await api.deleteBot(token, id);
      } catch {
        // ignore (e.g. 404)
      }
    }
    const bots = customBots.filter((b) => b.id !== id);
    setCustomBots(bots);
    if (selectedBotId === id) {
      if (bots.length) {
        setSelectedBotId(bots[0].id);
        setSidebarView("chat");
      } else {
        setSelectedBotId("add-bot");
        setSidebarView("add-bot");
      }
    }
    setDeleteConfirmBot(null);
  };

  const openRenameBot = (b: Bot) => {
    setMenuOpenBotId(null);
    setEditBotModal({ mode: "rename", id: b.id, initialName: b.name, value: b.name });
  };

  const openEditPersona = (b: Bot) => {
    setMenuOpenBotId(null);
    setEditBotModal({
      mode: "persona",
      id: b.id,
      initialDirection: (b.direction ?? "").toString(),
      value: (b.direction ?? "").toString(),
    });
  };

  const openEditFormOfAddress = (b: Bot) => {
    setMenuOpenBotId(null);
    setEditBotModal({
      mode: "formOfAddress",
      id: b.id,
      initialFormOfAddress: (b.form_of_address ?? "").toString(),
      value: (b.form_of_address ?? "").toString(),
    });
  };

  const saveEditBot = async () => {
    if (!token || !editBotModal) return;
    try {
      if (editBotModal.mode === "rename") {
        const newName = editBotModal.value.trim();
        if (!newName) throw new Error(tr("error.nameEmpty"));
        const updated = await api.updateBot(token, editBotModal.id, { name: newName });
        setCustomBots((prev) => prev.map((b) => (b.id === updated.id ? updated : b)));
      } else if (editBotModal.mode === "persona") {
        const newDir = editBotModal.value.trim();
        const updated = await api.updateBot(token, editBotModal.id, { direction: newDir });
        setCustomBots((prev) => prev.map((b) => (b.id === updated.id ? updated : b)));
      } else {
        const foa = editBotModal.value.trim();
        const updated = await api.updateBot(token, editBotModal.id, { form_of_address: foa || "" });
        setCustomBots((prev) => prev.map((b) => (b.id === updated.id ? updated : b)));
      }
      setEditBotModal(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.updateFailed"));
    }
  };

  const isAuthError = (err: unknown) =>
    err instanceof Error && /invalid|expired|token|unauthorized|401/i.test(err.message);

  const fetchRelationship = useCallback(async (t: string, botId: number) => {
    try {
      const rel = await api.relationship(t, botId);
      setRelationship(rel);
    } catch (err) {
      setRelationship(null);
      if (isAuthError(err)) {
        clearStoredToken();
        setToken(null);
      }
    }
  }, []);

  useEffect(() => {
    relationshipRef.current = relationship;
  }, [relationship]);

  const scheduleStatFlashReset = useCallback(() => {
    if (statFlashTimerRef.current) clearTimeout(statFlashTimerRef.current);
    statFlashTimerRef.current = setTimeout(() => {
      statFlashTimerRef.current = null;
      setTrustFlash(null);
      setResonanceFlash(null);
    }, 820);
  }, []);

  useEffect(
    () => () => {
      if (statFlashTimerRef.current) clearTimeout(statFlashTimerRef.current);
    },
    []
  );

  const retryConnection = useCallback(async () => {
    const t = getStoredToken();
    if (!t) return;
    setConnectionError(false);
    setBotsLoaded(false);
    setError("");
    const CONNECT_TIMEOUT_MS = 10000;
    try {
      const bots = await Promise.race([
        fetchBots(t),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("Connection timeout")), CONNECT_TIMEOUT_MS)
        ),
      ]);
      setBotsLoaded(true);
      setConnectionError(false);
      if (bots.length > 0) {
        setSelectedBotId(bots[0].id);
        setSidebarView("chat");
        await fetchRelationship(t, bots[0].id);
      } else {
        setSelectedBotId("add-bot");
        setSidebarView("add-bot");
      }
    } catch {
      setBotsLoaded(true);
      setConnectionError(true);
    }
  }, [fetchBots, fetchRelationship]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await api.login(authForm.username, authForm.password, rememberMe);
      setStoredToken(res.access_token, rememberMe);
      setToken(res.access_token);
      await fetchMe(res.access_token);
      const bots = await fetchBots(res.access_token);
      if (bots.length > 0) {
        setSelectedBotId(bots[0].id);
        setSidebarView("chat");
        await fetchRelationship(res.access_token, bots[0].id);
      } else {
        setSelectedBotId("add-bot");
        setSidebarView("add-bot");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.loginFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!authForm.display_name.trim()) {
      setError(tr("error.displayNameRequired"));
      return;
    }
    setLoading(true);
    try {
      await api.register(authForm.display_name, authForm.username, authForm.password);
      const res = await api.login(authForm.username, authForm.password, true);
      setStoredToken(res.access_token, true);
      setToken(res.access_token);
      await fetchMe(res.access_token);
      const bots = await fetchBots(res.access_token);
      if (bots.length > 0) {
        setSelectedBotId(bots[0].id);
        setSidebarView("chat");
        await fetchRelationship(res.access_token, bots[0].id);
      } else {
        setSelectedBotId("add-bot");
        setSidebarView("add-bot");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.registerFailed"));
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !input.trim()) return;
    if (sendingRef.current) return;
    sendingRef.current = true;
    const text = input.trim();
    setError("");
    setInput("");
    setLoading(true);
    setBotTyping(true);

    const bot = customBots.find((b) => b.id === selectedBotId);
    if (!bot) {
      setError(tr("error.botNotFound"));
      setLoading(false);
      setBotTyping(false);
      sendingRef.current = false;
      return;
    }

    const userMsg: Message = {
      id: -Date.now(),
      user_id: 0,
      session_id: 0,
      role: "user",
      content: text,
      created_at: new Date().toISOString(),
    };

    const applyRelationshipFromSend = (res: {
      trust: number;
      resonance: number;
      affection: number;
      openness: number;
      mood: string;
      display_name: string;
    }) => {
      const prevRel = relationshipRef.current;
      setRelationship({
        trust: res.trust,
        resonance: res.resonance,
        affection: res.affection,
        openness: res.openness,
        mood: res.mood,
        display_name: res.display_name || prevRel?.display_name || "",
      });
      setTrustFlash(null);
      setResonanceFlash(null);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (prevRel) {
            setTrustFlash(
              res.trust > prevRel.trust ? "up" : res.trust < prevRel.trust ? "down" : null
            );
            setResonanceFlash(
              res.resonance > prevRel.resonance
                ? "up"
                : res.resonance < prevRel.resonance
                  ? "down"
                  : null
            );
          }
          scheduleStatFlashReset();
        });
      });
    };

    if (activeGame && sidebarView === "chat" && selectedBotId !== "add-bot") {
      const game_messages = gomokuGameChat
        .filter((m) => m.role === "user" || m.role === "assistant")
        .map((m) => ({
          role: m.role as "user" | "assistant",
          content: m.content,
        }));
      setGomokuGameChat((prev) => sortMessagesByOrder([...prev, userMsg]));
      try {
        const relationship_events: string[] = [];
        if (gomokuRestartedWhileLosingRef.current) {
          relationship_events.push("user_restarted_while_losing");
        }
        if (gomokuPositionSummary?.game_over) {
          if (gomokuPositionSummary.match_result === "user_win") relationship_events.push("user_win");
          if (gomokuPositionSummary.match_result === "bot_win") relationship_events.push("bot_win");
        }
        const evs = gomokuPositionSummary?.events ?? [];
        if (evs.includes("user_created_threat")) relationship_events.push("user_created_strong_threat");
        if (evs.includes("user_blocked_bot_threat")) relationship_events.push("user_blocked_bot_threat");
        const seen = new Set<string>();
        const deduped_relationship_events = relationship_events.filter((e) => (seen.has(e) ? false : (seen.add(e), true)));
        const res = await api.sendBotMessage(
          token,
          selectedBotId as number,
          text,
          bot.system_prompt,
          0,
          0,
          false,
          {
            active_game: {
              type: "gomoku",
              difficulty: activeGame.difficulty,
              current_turn: activeGame.current_turn,
              bot_side: activeGame.bot_side,
            },
            game_messages,
            ...(gomokuPositionSummary ? { position_summary: gomokuPositionSummary } : {}),
            ...(deduped_relationship_events.length ? { relationship_events: deduped_relationship_events } : {}),
          }
        );
        const assistantMsg: Message = {
          id: -Date.now(),
          user_id: 0,
          session_id: 0,
          role: "assistant",
          content: res.assistant_reply || "",
          created_at: new Date().toISOString(),
        };
        setGomokuGameChat((prev) => sortMessagesByOrder([...prev, assistantMsg]));
        // Also append to the main transcript so it remains continuous after leaving the game.
        if (res.message_id != null) {
          const persistedUserMsg: Message = {
            ...userMsg,
            id: res.message_id,
            session_id: res.session_id,
          };
          const persistedAssistantMsg: Message = {
            ...assistantMsg,
            id: res.assistant_message_id ?? -Date.now(),
            session_id: res.session_id,
          };
          setMessages((prev) => sortMessagesByOrder([...prev, persistedUserMsg, persistedAssistantMsg]));
        }
        applyRelationshipFromSend(res);
        gomokuRestartedWhileLosingRef.current = false;
      } catch (err) {
        setError(err instanceof Error ? err.message : tr("error.sendFailed"));
        setGomokuGameChat((prev) => prev.slice(0, -1));
      } finally {
        setLoading(false);
        setBotTyping(false);
        sendingRef.current = false;
      }
      return;
    }

    setMessages((prev) => sortMessagesByOrder([...prev, userMsg]));
    try {
      const res = await api.sendBotMessage(token, selectedBotId as number, text, bot.system_prompt);
      const assistantMsg: Message = {
        id: -Date.now(),
        user_id: 0,
        session_id: 0,
        role: "assistant",
        content: res.assistant_reply || "",
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => sortMessagesByOrder([...prev, assistantMsg]));
      applyRelationshipFromSend(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.sendFailed"));
      setMessages((prev) => prev.slice(0, -1));
    } finally {
      setLoading(false);
      setBotTyping(false);
      sendingRef.current = false;
    }
  };

  const handleLogout = async () => {
    if (token) {
      try {
        await api.logout(token);
      } catch {}
      clearStoredToken();
    }
    setToken(null);
    setMessages([]);
    setRelationship(null);
    setMe(null);
    setUserMenuOpen(false);
  };

  const openRenameMe = () => {
    setUserMenuOpen(false);
    const current = me?.display_name?.trim() || relationship?.display_name?.trim() || "User";
    setEditMeModal({ mode: "rename", value: current });
  };

  const saveRenameMe = async () => {
    if (!token || !editMeModal) return;
    try {
      const newName = editMeModal.value.trim();
      if (!newName) throw new Error(tr("error.nameEmpty"));
      const updated = await api.updateMe(token, { display_name: newName });
      setMe(updated);
      setRelationship((prev) => (prev ? { ...prev, display_name: updated.display_name } : prev));
      setEditMeModal(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.updateFailed"));
    }
  };

  const readImageAsDataUrl = (file: File, onDone: (dataUrl: string) => void) => {
    const reader = new FileReader();
    reader.onload = () => onDone(reader.result as string);
    reader.readAsDataURL(file);
  };

  const triggerAvatarPick = () => avatarInputRef.current?.click();

  const onAvatarPicked = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !file.type.startsWith("image/") || !token) return;
    readImageAsDataUrl(file, (dataUrl) => setAvatarModal({ target: "user", dataUrl, dragging: false, error: "" }));
    e.target.value = "";
  };

  const openUserAvatarModal = () => {
    setUserMenuOpen(false);
    setAvatarModal({ target: "user", dataUrl: me?.avatar_data_url ?? null, dragging: false, error: "" });
  };

  const openBotAvatarModal = (b: Bot) => {
    setMenuOpenBotId(null);
    setAvatarModal({
      target: "bot",
      botId: b.id,
      botName: b.name,
      dataUrl: b.avatar_data_url ?? null,
      dragging: false,
      error: "",
    });
  };

  const saveAvatarModal = async () => {
    if (!token || !avatarModal) return;
    try {
      if (avatarModal.target === "user") {
        const updated = await api.updateMe(token, { avatar_data_url: avatarModal.dataUrl });
        setMe(updated);
      } else {
        const updated = await api.updateBot(token, avatarModal.botId, { avatar_data_url: avatarModal.dataUrl });
        setCustomBots((prev) => prev.map((x) => (x.id === updated.id ? updated : x)));
      }
      setAvatarModal(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.updateFailed"));
    }
  };

  const handleRefreshHistory = async () => {
    if (selectedBotId === "add-bot" || !token) return;
    try {
      const res = await api.historyBot(token, selectedBotId);
      setMessages(sortMessagesByOrder(res.messages ?? []));
    } catch {
      setMessages([]);
    }
  };

  const mapMessageList = (msgs: Message[]) =>
    msgs.map((m) =>
      m.role === "system" ? (
        <div key={m.id} className="msg-row msg-row-system msg-row-system-banner">
          <p className="msg-system-wechat-pill" role="status">
            <span className="sr-only">{tr("chat.system")}: </span>
            {m.content}
          </p>
        </div>
      ) : (
        <div key={m.id} className={`msg-row msg-row-${m.role}`}>
          {m.role === "assistant" && (
            <div className="msg-avatar msg-avatar-assistant msg-avatar-img" aria-hidden>
              <img
                src={customBots.find((b) => b.id === selectedBotId)?.avatar_data_url ?? "/avatar-assistant.png"}
                alt=""
                className="avatar-img"
              />
            </div>
          )}
          <div className={`msg msg-${m.role}`}>
            <span className="role">
              {m.role === "user"
                ? (relationship?.display_name?.trim() || tr("common.user"))
                : (customBots.find((b) => b.id === selectedBotId)?.name?.trim() || tr("chat.roleAssistant"))}
            </span>
            <span className="content">{m.content}</span>
          </div>
          {m.role === "user" && (
            <div className="msg-avatar msg-avatar-user" aria-hidden>
              <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z" />
              </svg>
            </div>
          )}
        </div>
      )
    );

  // Same output as server until mounted to avoid hydration mismatch
  if (!mounted) {
    return <div className="wrap">{tr("common.loading")}</div>;
  }

  if (!token) {
    return (
      <div className="wrap">
        <h1>{tr("common.chatbot")}</h1>
        <div className="user-menu-lang user-menu-lang-auth" aria-label={tr("lang.label")}>
          <span className="user-menu-lang-label">{tr("lang.label")}</span>
          <div className="user-menu-lang-toggles">
            <button
              type="button"
              className={`user-menu-lang-btn ${locale === "en" ? "active" : ""}`}
              onClick={() => setLocale("en")}
            >
              {tr("lang.en")}
            </button>
            <button
              type="button"
              className={`user-menu-lang-btn ${locale === "zh" ? "active" : ""}`}
              onClick={() => setLocale("zh")}
            >
              {tr("lang.zh")}
            </button>
          </div>
        </div>
        <div className="auth-tabs">
          <button
            type="button"
            className={authTab === "login" ? "active" : ""}
            onClick={() => setAuthTab("login")}
          >
            {tr("auth.login")}
          </button>
          <button
            type="button"
            className={authTab === "register" ? "active" : ""}
            onClick={() => setAuthTab("register")}
          >
            {tr("auth.register")}
          </button>
        </div>
        {authTab === "login" ? (
          <form onSubmit={handleLogin} className="auth-form">
            <input
              placeholder={tr("auth.usernamePh")}
              value={authForm.username}
              onChange={(e) => setAuthForm((f) => ({ ...f, username: filterUsername(e.target.value) }))}
              required
            />
            <div className="password-row">
              <input
                type={showPassword ? "text" : "password"}
                placeholder={tr("auth.passwordPh")}
                value={authForm.password}
                onChange={(e) => setAuthForm((f) => ({ ...f, password: filterPassword(e.target.value) }))}
                required
              />
              <button
                type="button"
                className="pw-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? tr("auth.hidePasswordAria") : tr("auth.showPasswordAria")}
              >
                {showPassword ? tr("common.hide") : tr("common.show")}
              </button>
            </div>
            <label className="remember-row">
              <input
                type="checkbox"
                checked={rememberMe}
                onChange={(e) => setRememberMe(e.target.checked)}
              />
              <span>{tr("auth.rememberMe")}</span>
            </label>
            <button type="submit" disabled={loading}>{tr("auth.login")}</button>
          </form>
        ) : (
          <form onSubmit={handleRegister} className="auth-form">
            <input
              placeholder={tr("auth.displayNamePh")}
              value={authForm.display_name}
              onChange={(e) => setAuthForm((f) => ({ ...f, display_name: e.target.value }))}
            />
            <input
              placeholder={tr("auth.usernamePh")}
              value={authForm.username}
              onChange={(e) => setAuthForm((f) => ({ ...f, username: filterUsername(e.target.value) }))}
              required
            />
            <div className="password-row">
              <input
                type={showPassword ? "text" : "password"}
                placeholder={tr("auth.passwordPh")}
                value={authForm.password}
                onChange={(e) => setAuthForm((f) => ({ ...f, password: filterPassword(e.target.value) }))}
                required
              />
              <button
                type="button"
                className="pw-toggle"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? tr("auth.hidePasswordAria") : tr("auth.showPasswordAria")}
              >
                {showPassword ? tr("common.hide") : tr("common.show")}
              </button>
            </div>
            <button type="submit" disabled={loading}>{tr("auth.register")}</button>
          </form>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    );
  }

  return (
    <div className={`app-with-sidebar ${sidebarOpen ? "sidebar-overlay-open" : ""}`}>
      {sidebarOpen && (
        <div
          className="sidebar-backdrop"
          role="button"
          tabIndex={0}
          aria-label={tr("nav.closeMenu")}
          onClick={() => setSidebarOpen(false)}
          onKeyDown={(e) => e.key === "Enter" && setSidebarOpen(false)}
        />
      )}
      <aside className="sidebar">
        <div className="sidebar-header-row">
          <div className="sidebar-brand">{tr("common.chatbot")}</div>
          <button
            type="button"
            className="sidebar-close-btn"
            aria-label={tr("nav.closeSidebar")}
            onClick={() => setSidebarOpen(false)}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M18 6L6 18M6 6l12 12" />
            </svg>
          </button>
        </div>
        <nav className="sidebar-nav">
          <div className="sidebar-section">{tr("nav.bots")}</div>
          <div className="sidebar-bots-list">
            {customBots.map((b) => (
              <div
                key={b.id}
                className={`sidebar-bot-row ${sidebarView === "chat" && selectedBotId === b.id ? "active" : ""} ${menuOpenBotId === b.id ? "menu-open" : ""}`}
                ref={menuOpenBotId === b.id ? menuRef : undefined}
              >
                <button
                  type="button"
                  className="sidebar-bot-item"
                  onClick={() => { setSidebarView("chat"); setSelectedBotId(b.id); setMenuOpenBotId(null); setSidebarOpen(false); }}
                >
                  <span className="sidebar-bot-avatar" aria-hidden="true">
                    {b.avatar_data_url ? (
                      <img src={b.avatar_data_url} alt="" />
                    ) : (
                      <span className="sidebar-bot-avatar-fallback">
                        {(b.name?.trim()?.[0] ?? "?").toUpperCase()}
                      </span>
                    )}
                  </span>
                  <span className="sidebar-bot-name">{b.name}</span>
                </button>
                <button
                  type="button"
                  className="sidebar-bot-menu"
                  aria-label={tr("nav.botOptions")}
                  onClick={(e) => { e.stopPropagation(); setMenuOpenBotId((prev) => (prev === b.id ? null : b.id)); }}
                >
                  <span className="sidebar-bot-menu-dots">⋯</span>
                </button>
                {menuOpenBotId === b.id && (
                  <div className="sidebar-bot-dropdown">
                    <button type="button" className="sidebar-bot-dropdown-item" onClick={() => openRenameBot(b)}>
                      {tr("sidebar.rename")}
                    </button>
                    <button type="button" className="sidebar-bot-dropdown-item" onClick={() => openEditPersona(b)}>
                      {tr("sidebar.editDirection")}
                    </button>
                    <button type="button" className="sidebar-bot-dropdown-item" onClick={() => openEditFormOfAddress(b)}>
                      {tr("sidebar.editFormOfAddress")}
                    </button>
                    <button type="button" className="sidebar-bot-dropdown-item" onClick={() => openBotAvatarModal(b)}>
                      {tr("sidebar.changeAvatar")}
                    </button>
                    <button type="button" className="sidebar-bot-dropdown-item" onClick={() => handleDeleteBot(b.id, b.name)}>
                      {tr("common.delete")}
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
          <button
            type="button"
            className={sidebarView === "add-bot" || selectedBotId === "add-bot" ? "active" : ""}
            onClick={() => { setSidebarView("add-bot"); setSelectedBotId("add-bot"); setSidebarOpen(false); }}
          >
            {tr("nav.addBot")}
          </button>
        </nav>
      </aside>
      <main className="main-content">
        <header className="app-topbar">
          <button
            type="button"
            className="topbar-hamburger"
            aria-label={tr("nav.openMenu")}
            aria-expanded={sidebarOpen}
            onClick={() => setSidebarOpen(true)}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <div className="app-topbar-right">
            <div className="user-menu" ref={userMenuRef}>
              <button
                type="button"
                className="user-menu-trigger"
                onClick={() => setUserMenuOpen((v) => !v)}
              >
                <span className="user-menu-avatar" aria-hidden="true">
                  {me?.avatar_data_url ? (
                    <img src={me.avatar_data_url} alt="" />
                  ) : (
                    <span className="user-menu-avatar-fallback">
                      {(me?.display_name?.trim()?.[0] ?? relationship?.display_name?.trim()?.[0] ?? "U").toUpperCase()}
                    </span>
                  )}
                </span>
                <span className="user-menu-name">
                  {me?.display_name?.trim() || relationship?.display_name?.trim() || tr("common.user")}
                </span>
              </button>

              <input
                ref={avatarInputRef}
                type="file"
                accept="image/*"
                onChange={onAvatarPicked}
                style={{ display: "none" }}
              />

              {userMenuOpen && (
                <div className="user-menu-dropdown">
                  <div className="user-menu-lang" aria-label={tr("lang.label")}>
                    <span className="user-menu-lang-label">{tr("lang.label")}</span>
                    <div className="user-menu-lang-toggles">
                      <button
                        type="button"
                        className={`user-menu-lang-btn ${locale === "en" ? "active" : ""}`}
                        onClick={() => setLocale("en")}
                      >
                        {tr("lang.en")}
                      </button>
                      <button
                        type="button"
                        className={`user-menu-lang-btn ${locale === "zh" ? "active" : ""}`}
                        onClick={() => setLocale("zh")}
                      >
                        {tr("lang.zh")}
                      </button>
                    </div>
                  </div>
                  <div className="user-menu-sep" />
                  <button type="button" className="user-menu-item" onClick={openRenameMe}>
                    {tr("userMenu.rename")}
                  </button>
                  <button type="button" className="user-menu-item" onClick={openUserAvatarModal}>
                    {tr("userMenu.changeAvatar")}
                  </button>
                  <div className="user-menu-sep" />
                  <button type="button" className="user-menu-item user-menu-item-danger" onClick={handleLogout}>
                    {tr("userMenu.logout")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        {sidebarView === "chat" && (
          <>
            {!gomokuBoardOpen ? (
              <div className="wrap chat-wrap">
                <header className="chat-header">
                  {(() => {
                    const profileBot = customBots.find((b) => b.id === selectedBotId);
                    return (
                      <button
                        type="button"
                        className="chat-header-bot-trigger"
                        onClick={() => profileBot && setBotProfileOpen(true)}
                        aria-expanded={botProfileOpen}
                        aria-haspopup="dialog"
                        disabled={!profileBot}
                      >
                        <span className="chat-header-bot-avatar" aria-hidden>
                          {profileBot?.avatar_data_url ? (
                            <img src={profileBot.avatar_data_url} alt="" className="avatar-img" />
                          ) : (
                            <span className="chat-header-bot-avatar-fallback">
                              {(profileBot?.name?.trim()?.[0] ?? "?").toUpperCase()}
                            </span>
                          )}
                        </span>
                        <span className="chat-header-bot-name">{profileBot?.name ?? tr("chat.fallbackTitle")}</span>
                      </button>
                    );
                  })()}
                  <div className="chat-header-right">
                    {relationship && (
                      <div className="status-bar" ref={statExplainRootRef} role="status" aria-live="polite">
                        <div className="stat-chip-wrap">
                          <button
                            type="button"
                            className={`stat-chip ${statExplainOpen === "trust" ? "stat-chip-active" : ""}`}
                            aria-expanded={statExplainOpen === "trust"}
                            aria-controls="stat-popover-trust"
                            id="stat-trigger-trust"
                            onClick={() =>
                              setStatExplainOpen((o) => (o === "trust" ? null : "trust"))
                            }
                          >
                            {tr("stats.trust")}{" "}
                            <span
                              className={`stat-chip-value${trustFlash === "up" ? " stat-chip-value-flash-up" : ""}${trustFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
                            >
                              {relationship.trust}
                            </span>
                          </button>
                          {statExplainOpen === "trust" && (
                            <div
                              id="stat-popover-trust"
                              className="stat-popover"
                              role="dialog"
                              aria-labelledby="stat-trigger-trust"
                            >
                              <div className="stat-popover-accent" aria-hidden />
                              <div className="stat-popover-head">
                                <span className="stat-popover-label">{tr("stats.trust")}</span>
                                <span
                                  className={`stat-popover-num${trustFlash === "up" ? " stat-chip-value-flash-up" : ""}${trustFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
                                >
                                  {relationship.trust}
                                </span>
                              </div>
                              <p className="stat-popover-text">
                                {trustTierDescription(relationship.trust, tr)}
                              </p>
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
                            onClick={() =>
                              setStatExplainOpen((o) => (o === "resonance" ? null : "resonance"))
                            }
                          >
                            {tr("stats.resonance")}{" "}
                            <span
                              className={`stat-chip-value${resonanceFlash === "up" ? " stat-chip-value-flash-up" : ""}${resonanceFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
                            >
                              {relationship.resonance}
                            </span>
                          </button>
                          {statExplainOpen === "resonance" && (
                            <div
                              id="stat-popover-resonance"
                              className="stat-popover"
                              role="dialog"
                              aria-labelledby="stat-trigger-resonance"
                            >
                              <div className="stat-popover-accent stat-popover-accent-resonance" aria-hidden />
                              <div className="stat-popover-head">
                                <span className="stat-popover-label">{tr("stats.resonance")}</span>
                                <span
                                  className={`stat-popover-num${resonanceFlash === "up" ? " stat-chip-value-flash-up" : ""}${resonanceFlash === "down" ? " stat-chip-value-flash-down" : ""}`}
                                >
                                  {relationship.resonance}
                                </span>
                              </div>
                              <p className="stat-popover-text">
                                {resonanceTierDescription(relationship.resonance, tr)}
                              </p>
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
                    )}
                    <button type="button" onClick={handleRefreshHistory} className="btn-sm btn-refresh">
                      {tr("chat.refresh")}
                    </button>
                  </div>
                </header>
                {gomokuSessionSinceMs != null && <GomokuGameResumeBar tr={tr} onShowBoard={() => setGomokuBoardOpen(true)} />}
                <div className="messages" ref={messagesRef}>
                  {(() => {
                    const thread =
                      gomokuSessionSinceMs != null ? gomokuCompanionMessages : sortMessagesByOrder(messages);
                    return (
                      <>
                        {thread.length === 0 && <p className="muted">{tr("chat.noMessages")}</p>}
                        {mapMessageList(thread)}
                      </>
                    );
                  })()}
                  {botTyping && (
                    <div className="msg-row msg-row-assistant" aria-live="polite" aria-label={tr("chat.typing").replace("{name}", customBots.find((b) => b.id === selectedBotId)?.name ?? tr("chat.roleAssistant"))}>
                      <div className="msg-avatar msg-avatar-assistant msg-avatar-img" aria-hidden>
                        <img
                          src={customBots.find((b) => b.id === selectedBotId)?.avatar_data_url ?? "/avatar-assistant.png"}
                          alt=""
                          className="avatar-img"
                        />
                      </div>
                      <div className="msg msg-assistant">
                        <span className="role">{customBots.find((b) => b.id === selectedBotId)?.name?.trim() || tr("chat.roleAssistant")}</span>
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
                <form onSubmit={handleSend} className="send-form">
                  <div className="send-form-inner">
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
                      rows={1}
                      className="send-input"
                    />
                    <div className="send-form-row">
                      <GamesMenu variant="chat" tr={tr} onPickGomoku={() => setGomokuModalOpen(true)} />
                      <div className="send-form-send-slot">
                        <button
                          type="submit"
                          className="send-btn-icon"
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
                {error && <p className="error">{error}</p>}
              </div>
            ) : (
              <GomokuGamePlayingView
                tr={tr}
                locale={locale}
                matchKey={gomokuSessionSinceMs ?? 0}
                onQuit={handleGomokuQuit}
                onHideBoard={() => setGomokuBoardOpen(false)}
                onRequestGomokuModal={() => setGomokuModalOpen(true)}
                customBots={customBots}
                selectedBotId={selectedBotId as number}
                setBotProfileOpen={setBotProfileOpen}
                botProfileOpen={botProfileOpen}
                relationship={relationship}
                statExplainRootRef={statExplainRootRef}
                statExplainOpen={statExplainOpen}
                setStatExplainOpen={setStatExplainOpen}
                trustFlash={trustFlash}
                resonanceFlash={resonanceFlash}
                trustTierDescription={(t) => trustTierDescription(t, tr)}
                resonanceTierDescription={(r) => resonanceTierDescription(r, tr)}
                messagesRef={messagesRef}
                companionMessages={gomokuCompanionMessages}
                mapMessageList={mapMessageList}
                botTyping={botTyping}
                handleSend={handleSend}
                input={input}
                setInput={setInput}
                loading={loading}
                sendInputRef={sendInputRef}
                error={error}
                gomokuAiDifficulty={gomokuAiDifficulty}
                onGomokuAiDifficultyChange={syncGomokuDifficulty}
                onGomokuTurnChange={setGomokuTurn}
                onGomokuBoardRestart={handleGomokuBoardRestart}
                appendGomokuGameAssistantText={appendGomokuGameAssistantText}
                onGomokuBoardSnapshot={handleGomokuBoardSnapshot}
              />
            )}
          </>
        )}
        {sidebarView === "add-bot" && !botsLoaded && (
          <div className="connection-error-wrap connection-loading-wrap" role="status" aria-live="polite">
            <p className="connection-error-text">{tr("connection.connecting")}</p>
            <div className="connection-loading-spinner" aria-hidden />
          </div>
        )}
        {sidebarView === "add-bot" && botsLoaded && connectionError && (
          <div className="connection-error-wrap" role="alert">
            <h2 className="connection-error-title">{tr("connection.unableTitle")}</h2>
            <p className="connection-error-text">
              {tr("connection.unableBody")}
            </p>
            <button type="button" className="connection-error-retry" onClick={retryConnection}>
              {tr("common.retry")}
            </button>
          </div>
        )}
        {sidebarView === "add-bot" && botsLoaded && !connectionError && (
          <AddBotView
            token={token}
            botCount={customBots.length}
            onSaved={async (created) => {
              if (!token) return;
              await fetchBots(token);
              setSelectedBotId(created.id);
              setSidebarView("chat");
              await fetchRelationship(token, created.id);
            }}
          />
        )}
      </main>
      {botProfileOpen &&
        selectedBotId !== "add-bot" &&
        (() => {
          const b = customBots.find((x) => x.id === selectedBotId);
          if (!b) return null;
          const styleSummary = relationship
            ? generateCurrentStyleSummary({
                trust: relationship.trust,
                resonance: relationship.resonance,
                affection: relationship.affection,
                openness: relationship.openness,
                mood: relationship.mood,
                direction: (b.direction ?? "").toString(),
              })
            : null;
          return (
            <div
              className="modal-overlay bot-profile-overlay"
              role="dialog"
              aria-modal="true"
              aria-labelledby="bot-profile-title"
            >
              <div className="modal-dialog bot-profile-dialog" onClick={(e) => e.stopPropagation()}>
                <div className="bot-profile-dialog-top">
                  <div className="bot-profile-dialog-identity">
                    <span className="bot-profile-dialog-avatar" aria-hidden>
                      {b.avatar_data_url ? (
                        <img src={b.avatar_data_url} alt="" className="avatar-img" />
                      ) : (
                        <span className="bot-profile-dialog-avatar-fallback">
                          {(b.name?.trim()?.[0] ?? "?").toUpperCase()}
                        </span>
                      )}
                    </span>
                    <div className="bot-profile-dialog-name-block">
                      {botProfileNameEditing ? (
                        <div className="bot-profile-header-name-edit">
                          <input
                            id="bot-profile-title"
                            className="bot-profile-header-name-input"
                            value={botProfileNameDraft}
                            onChange={(e) => setBotProfileNameDraft(e.target.value)}
                            disabled={botProfileNameSaving}
                            autoFocus
                            aria-label={tr("profile.botNameAria")}
                          />
                          <div className="bot-profile-inline-actions">
                            <button
                              type="button"
                              className="bot-profile-persona-cancel"
                              disabled={botProfileNameSaving}
                              onClick={() => setBotProfileNameEditing(false)}
                            >
                              {tr("common.cancel")}
                            </button>
                            <button
                              type="button"
                              className="bot-profile-persona-save"
                              disabled={botProfileNameSaving}
                              onClick={() => saveBotNameFromProfile(b.id)}
                            >
                              {botProfileNameSaving ? tr("common.saving") : tr("common.save")}
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="bot-profile-dialog-name-row">
                          <h2 id="bot-profile-title" className="bot-profile-dialog-title">
                            {b.name}
                          </h2>
                          <button
                            type="button"
                            className="bot-profile-edit-icon"
                            aria-label={tr("profile.editBotName")}
                            onClick={() => {
                              setBotProfileNameDraft(b.name);
                              setBotProfileNameEditing(true);
                            }}
                          >
                            <svg
                              width="18"
                              height="18"
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              strokeWidth="2"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              aria-hidden
                            >
                              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                            </svg>
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    className="bot-profile-close"
                    onClick={() => setBotProfileOpen(false)}
                    aria-label={tr("profile.close")}
                  >
                    ×
                  </button>
                </div>
                <div className="bot-profile-scroll">
                  <section className="bot-profile-section">
                    <div className="bot-profile-section-head">
                      <div className="bot-profile-section-title-with-help">
                        <h3 className="bot-profile-section-title">{tr("profile.formOfAddress")}</h3>
                        <span className="bot-profile-tooltip-host">
                          <button
                            type="button"
                            className="bot-profile-help-trigger"
                            aria-label={tr("profile.formOfAddressHelpAria")}
                            aria-describedby="bot-profile-foa-tip"
                          >
                            <span aria-hidden>?</span>
                          </button>
                          <span
                            id="bot-profile-foa-tip"
                            className="bot-profile-tooltip"
                            role="tooltip"
                          >
                            {tr("profile.formOfAddressTip")}
                          </span>
                        </span>
                      </div>
                      {!botProfileFoaEditing && (
                        <button
                          type="button"
                          className="bot-profile-edit-icon"
                          aria-label={tr("profile.editFormOfAddress")}
                          onClick={() => {
                            setBotProfileFoaDraft((b.form_of_address ?? "").toString());
                            setBotProfileFoaEditing(true);
                          }}
                        >
                          <svg
                            width="18"
                            height="18"
                            viewBox="0 0 24 24"
                            fill="none"
                            stroke="currentColor"
                            strokeWidth="2"
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            aria-hidden
                          >
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                          </svg>
                        </button>
                      )}
                    </div>
                    {botProfileFoaEditing ? (
                      <div className="bot-profile-foa-edit">
                        <label className="bot-profile-interest-label" htmlFor="bot-profile-foa-input">
                          {tr("profile.howBotAddresses")}
                        </label>
                        <input
                          id="bot-profile-foa-input"
                          className="bot-profile-foa-input"
                          type="text"
                          value={botProfileFoaDraft}
                          onChange={(e) => setBotProfileFoaDraft(e.target.value)}
                          placeholder={tr("profile.foaPlaceholder")}
                          disabled={botProfileFoaSaving}
                          autoFocus
                        />
                        <div className="bot-profile-persona-actions">
                          <button
                            type="button"
                            className="bot-profile-persona-cancel"
                            disabled={botProfileFoaSaving}
                            onClick={() => setBotProfileFoaEditing(false)}
                          >
                            {tr("common.cancel")}
                          </button>
                          <button
                            type="button"
                            className="bot-profile-persona-save"
                            disabled={botProfileFoaSaving}
                            onClick={() => saveBotFoaFromProfile(b.id)}
                          >
                            {botProfileFoaSaving ? tr("common.saving") : tr("common.save")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <p className="bot-profile-section-body">
                        {(b.form_of_address ?? "").trim() ||
                          tr("profile.foaEmpty")}
                      </p>
                    )}
                  </section>
                  <section className="bot-profile-section">
                    <div className="bot-profile-section-head">
                      <h3 className="bot-profile-section-title">{tr("profile.direction")}</h3>
                      {!botProfilePersonaEditing && (
                        <button
                          type="button"
                          className="bot-profile-edit-icon"
                          aria-label={tr("profile.editDirection")}
                          onClick={() => {
                            setBotProfilePersonaDraft((b.direction ?? "").toString());
                            setBotProfilePersonaEditing(true);
                          }}
                        >
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                          </svg>
                        </button>
                      )}
                    </div>
                    {botProfilePersonaEditing ? (
                      <div className="bot-profile-persona-edit">
                        <textarea
                          className="bot-profile-persona-textarea"
                          value={botProfilePersonaDraft}
                          onChange={(e) => setBotProfilePersonaDraft(e.target.value)}
                          rows={5}
                          placeholder={tr("profile.directionPlaceholder")}
                          disabled={botProfilePersonaSaving}
                          autoFocus
                        />
                        <div className="bot-profile-persona-actions">
                          <button
                            type="button"
                            className="bot-profile-persona-cancel"
                            disabled={botProfilePersonaSaving}
                            onClick={() => setBotProfilePersonaEditing(false)}
                          >
                            {tr("common.cancel")}
                          </button>
                          <button
                            type="button"
                            className="bot-profile-persona-save"
                            disabled={botProfilePersonaSaving}
                            onClick={() => saveBotPersonaFromProfile(b.id)}
                          >
                            {botProfilePersonaSaving ? tr("common.saving") : tr("common.save")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <p className="bot-profile-section-body">
                        {(b.direction ?? "").trim() ||
                          tr("profile.directionEmpty")}
                      </p>
                    )}
                  </section>
                  <section className="bot-profile-section">
                    <div className="bot-profile-section-head">
                      <div className="bot-profile-section-title-with-help">
                        <h3 className="bot-profile-section-title">{tr("profile.interests")}</h3>
                        <span className="bot-profile-tooltip-host">
                          <button
                            type="button"
                            className="bot-profile-help-trigger"
                            aria-label={tr("profile.interestsHelpAria")}
                            aria-describedby="bot-profile-interests-tip"
                          >
                            <span aria-hidden>?</span>
                          </button>
                          <span
                            id="bot-profile-interests-tip"
                            className="bot-profile-tooltip"
                            role="tooltip"
                          >
                            {tr("interests.intro")}
                          </span>
                        </span>
                      </div>
                      {!botProfileInterestsEditing && (
                        <button
                          type="button"
                          className="bot-profile-edit-icon"
                          aria-label={tr("profile.editInterests")}
                          onClick={() => {
                            const p = (b.primary_interest ?? "").toString().trim();
                            setBotProfilePrimaryDraft(
                              p || DEFAULT_PRIMARY_INTEREST_KEY
                            );
                            setBotProfileSecondaryDraft(
                              Array.isArray(b.secondary_interests) ? [...b.secondary_interests] : []
                            );
                            setBotProfileInterestsEditing(true);
                          }}
                        >
                          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
                          </svg>
                        </button>
                      )}
                    </div>
                    {botProfileInterestsEditing ? (
                      <div className="bot-profile-interests-edit">
                        <label className="bot-profile-interest-label">{tr("profile.primaryInterest")}</label>
                        <div className="interest-chip-grid" role="radiogroup" aria-label={tr("profile.primaryInterestAria")}>
                          {PRIMARY_INTEREST_OPTIONS.map((o) => {
                            const on = botProfilePrimaryDraft === o.key;
                            return (
                              <button
                                key={o.key}
                                type="button"
                                role="radio"
                                className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                                disabled={botProfileInterestsSaving}
                                aria-checked={on}
                                onClick={() => {
                                  setBotProfilePrimaryDraft(o.key);
                                  setBotProfileSecondaryDraft((prev) => prev.filter((k) => k !== o.key));
                                }}
                              >
                                {tr(`interest.${o.key}`)}
                              </button>
                            );
                          })}
                        </div>
                        <label className="bot-profile-interest-label">{tr("profile.secondaryInterests")}</label>
                        <div className="interest-chip-grid" role="group" aria-label={tr("profile.secondaryInterestsAria")}>
                          {SECONDARY_INTEREST_OPTIONS.map((o) => {
                            const on = botProfileSecondaryDraft.includes(o.key);
                            const disabled =
                              botProfileInterestsSaving ||
                              (!on && botProfileSecondaryDraft.length >= 3) ||
                              o.key === botProfilePrimaryDraft;
                            return (
                              <button
                                key={o.key}
                                type="button"
                                className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                                disabled={disabled}
                                onClick={() => {
                                  setBotProfileSecondaryDraft((prev) =>
                                    prev.includes(o.key)
                                      ? prev.filter((k) => k !== o.key)
                                      : prev.length < 3
                                        ? [...prev, o.key]
                                        : prev
                                  );
                                }}
                              >
                                {tr(`interest.${o.key}`)}
                              </button>
                            );
                          })}
                        </div>
                        <div className="bot-profile-persona-actions">
                          <button
                            type="button"
                            className="bot-profile-persona-cancel"
                            disabled={botProfileInterestsSaving}
                            onClick={() => setBotProfileInterestsEditing(false)}
                          >
                            {tr("common.cancel")}
                          </button>
                          <button
                            type="button"
                            className="bot-profile-persona-save"
                            disabled={botProfileInterestsSaving}
                            onClick={() => saveBotInterestsFromProfile(b.id)}
                          >
                            {botProfileInterestsSaving ? tr("common.saving") : tr("common.save")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="bot-profile-interests-read">
                        <div className="bot-profile-interest-read-row">
                          <strong className="bot-profile-interest-read-label">{tr("profile.primaryLabel")}</strong>
                          <div
                            className="bot-profile-style-tags bot-profile-interest-read-tags"
                            aria-label={tr("profile.primaryInterestAria")}
                          >
                            <span className="bot-profile-style-tag">
                              {tr(
                                `interest.${
                                  (b.primary_interest ?? "").toString().trim() ||
                                  DEFAULT_PRIMARY_INTEREST_KEY
                                }`
                              )}
                            </span>
                            {!(b.primary_interest ?? "").toString().trim() && (
                              <span className="bot-profile-muted bot-profile-interest-read-note">
                                {tr("profile.notSavedYet")}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="bot-profile-interest-read-row">
                          <strong className="bot-profile-interest-read-label">{tr("profile.secondaryLabel")}</strong>
                          <div
                            className="bot-profile-style-tags bot-profile-interest-read-tags"
                            aria-label={tr("profile.secondaryInterestsAria")}
                          >
                            {(b.secondary_interests?.length
                              ? b.secondary_interests
                              : []
                            ).map((k) => (
                              <span key={k} className="bot-profile-style-tag">
                                {tr(`interest.${k}`)}
                              </span>
                            ))}
                            {!(b.secondary_interests?.length) && (
                              <span className="bot-profile-muted bot-profile-interest-read-note">
                                {tr("profile.none")}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    )}
                  </section>
                  <section className="bot-profile-section">
                    <div className="bot-profile-section-head">
                      <div className="bot-profile-section-title-with-help">
                        <h3 className="bot-profile-section-title">{tr("profile.initiative")}</h3>
                        <span className="bot-profile-tooltip-host">
                          <button
                            type="button"
                            className="bot-profile-help-trigger"
                            aria-label={tr("profile.initiativeHelpAria")}
                            aria-describedby="bot-profile-initiative-tip"
                          >
                            <span aria-hidden>?</span>
                          </button>
                          <span
                            id="bot-profile-initiative-tip"
                            className="bot-profile-tooltip"
                            role="tooltip"
                          >
                            {tr("initiative.tooltip")}
                          </span>
                        </span>
                      </div>
                      {!botProfileInitiativeEditing && (
                        <button
                          type="button"
                          className="bot-profile-edit-icon"
                          aria-label={tr("profile.editInitiative")}
                          onClick={() => {
                            setBotProfileInitiativeDraft(
                              normalizeInitiativeLevel(b.initiative)
                            );
                            setBotProfileInitiativeEditing(true);
                          }}
                        >
                          <span aria-hidden>✎</span>
                        </button>
                      )}
                    </div>
                    {botProfileInitiativeEditing ? (
                      <div className="bot-profile-interests-edit">
                        <div className="interest-chip-grid" role="radiogroup" aria-label={tr("profile.initiativeLevelAria")}>
                          {INITIATIVE_OPTIONS.map((o) => {
                            const on = botProfileInitiativeDraft === o.key;
                            return (
                              <button
                                key={o.key}
                                type="button"
                                role="radio"
                                className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                                aria-checked={on}
                                disabled={botProfileInitiativeSaving}
                                onClick={() => setBotProfileInitiativeDraft(o.key)}
                              >
                                {tr(`initiative.${o.key}`)}
                              </button>
                            );
                          })}
                        </div>
                        <div className="bot-profile-persona-actions">
                          <button
                            type="button"
                            className="bot-profile-persona-cancel"
                            disabled={botProfileInitiativeSaving}
                            onClick={() => setBotProfileInitiativeEditing(false)}
                          >
                            {tr("common.cancel")}
                          </button>
                          <button
                            type="button"
                            className="bot-profile-persona-save"
                            disabled={botProfileInitiativeSaving}
                            onClick={() => saveBotInitiativeFromProfile(b.id)}
                          >
                            {botProfileInitiativeSaving ? tr("common.saving") : tr("common.save")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="bot-profile-interests-read">
                        <div className="bot-profile-interest-read-row">
                          <strong className="bot-profile-interest-read-label">{tr("profile.baseLevel")}</strong>
                          <div
                            className="bot-profile-style-tags bot-profile-interest-read-tags"
                            aria-label={tr("profile.baseInitiativeAria")}
                          >
                            <span className="bot-profile-style-tag">
                              {tr(`initiative.${normalizeInitiativeLevel(b.initiative)}`)}
                            </span>
                          </div>
                        </div>
                      </div>
                    )}
                  </section>
                  <section className="bot-profile-section">
                    <div className="bot-profile-section-head">
                      <div className="bot-profile-section-title-with-help">
                        <h3 className="bot-profile-section-title">{tr("profile.gameReplyStyle")}</h3>
                        <span className="bot-profile-tooltip-host">
                          <button
                            type="button"
                            className="bot-profile-help-trigger"
                            aria-label={tr("profile.gameReplyStyleHelpAria")}
                            aria-describedby="bot-profile-game-reply-tip"
                          >
                            <span aria-hidden>?</span>
                          </button>
                          <span
                            id="bot-profile-game-reply-tip"
                            className="bot-profile-tooltip"
                            role="tooltip"
                          >
                            {tr("profile.gameReplyStyleTip")}
                          </span>
                        </span>
                      </div>
                      {!botProfileGameReplyEditing && (
                        <button
                          type="button"
                          className="bot-profile-edit-icon"
                          aria-label={tr("profile.editGameReplyStyle")}
                          onClick={() => {
                            setBotProfileGameReplyDraft(normalizeGameReplyStyle(b.personality));
                            setBotProfileGameReplyEditing(true);
                          }}
                        >
                          <span aria-hidden>✎</span>
                        </button>
                      )}
                    </div>
                    {botProfileGameReplyEditing ? (
                      <div className="bot-profile-interests-edit">
                        <div
                          className="interest-chip-grid"
                          role="radiogroup"
                          aria-label={tr("profile.gameReplyStyleAria")}
                        >
                          {GAME_REPLY_STYLE_OPTIONS.map(({ key: k }) => {
                            const on = botProfileGameReplyDraft === k;
                            return (
                              <button
                                key={k}
                                type="button"
                                role="radio"
                                className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                                aria-checked={on}
                                disabled={botProfileGameReplySaving}
                                onClick={() => setBotProfileGameReplyDraft(k)}
                              >
                                {tr(`gameReplyStyle.${k}`)}
                              </button>
                            );
                          })}
                        </div>
                        <div className="bot-profile-persona-actions">
                          <button
                            type="button"
                            className="bot-profile-persona-cancel"
                            disabled={botProfileGameReplySaving}
                            onClick={() => setBotProfileGameReplyEditing(false)}
                          >
                            {tr("common.cancel")}
                          </button>
                          <button
                            type="button"
                            className="bot-profile-persona-save"
                            disabled={botProfileGameReplySaving}
                            onClick={() => saveBotGameReplyFromProfile(b.id, botProfileGameReplyDraft)}
                          >
                            {botProfileGameReplySaving ? tr("common.saving") : tr("common.save")}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="bot-profile-interests-read">
                        <div
                          className="bot-profile-style-tags bot-profile-interest-read-tags"
                          aria-label={tr("profile.gameReplyStyleAria")}
                        >
                          <span className="bot-profile-style-tag">
                            {tr(`gameReplyStyle.${normalizeGameReplyStyle(b.personality)}`)}
                          </span>
                        </div>
                      </div>
                    )}
                  </section>
                  <section className="bot-profile-section">
                    <h3 className="bot-profile-section-title">{tr("profile.styleSummary")}</h3>
                    {styleSummary ? (
                      <>
                        <div className="bot-profile-style-tags" aria-label={tr("profile.styleTagsAria")}>
                          {styleSummary.tags.map((tag, i) => (
                            <span key={`${tag}-${i}`} className="bot-profile-style-tag">
                              {tag}
                            </span>
                          ))}
                        </div>
                        <p className="bot-profile-section-body bot-profile-style-paragraph">
                          {styleSummary.paragraph}
                        </p>
                      </>
                    ) : (
                      <p className="bot-profile-muted">
                        {tr("profile.styleSummaryEmpty")}
                      </p>
                    )}
                  </section>
                  <section className="bot-profile-section">
                    <h3 className="bot-profile-section-title">{tr("profile.relationship")}</h3>
                    {relationship ? (
                      <div className="bot-profile-rel">
                        <p>
                          <strong>{tr("stats.trust")} {relationship.trust}</strong> —{" "}
                          {trustTierDescription(relationship.trust, tr)}
                        </p>
                        <p>
                          <strong>{tr("stats.resonance")} {relationship.resonance}</strong> —{" "}
                          {resonanceTierDescription(relationship.resonance, tr)}
                        </p>
                        <p>
                          <strong>{tr("profile.currentMood")}</strong>{" "}
                          <span
                            className="bot-profile-mood-value mood-tooltip-host mood-tooltip-host-inline"
                            tabIndex={0}
                          >
                            {relationship.mood}
                            <span className="bot-profile-tooltip mood-tooltip-popover" role="tooltip">
                              {moodTooltip(relationship.mood, locale)}
                            </span>
                          </span>
                        </p>
                      </div>
                    ) : (
                      <p className="bot-profile-muted">
                        {tr("profile.relationshipEmpty")}
                      </p>
                    )}
                  </section>
                  <section className="bot-profile-section">
                    <h3 className="bot-profile-section-title">{tr("profile.memory")}</h3>
                    <p className="bot-profile-muted">
                      {tr("profile.memoryBody")}
                    </p>
                  </section>
                </div>
              </div>
            </div>
          );
        })()}
      {deleteConfirmBot && (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="delete-bot-title">
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h2 id="delete-bot-title" className="modal-title">{tr("modal.deleteBotTitle")}</h2>
            <p className="modal-body">
              {(() => {
                const parts = tr("modal.deleteBotBody").split("{name}");
                return (
                  <>
                    {parts[0]}
                    <strong>{deleteConfirmBot.name}</strong>
                    {parts[1] ?? ""}
                  </>
                );
              })()}
            </p>
            <div className="modal-actions">
              <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setDeleteConfirmBot(null)}>
                {tr("common.cancel")}
              </button>
              <button type="button" className="modal-btn modal-btn-delete" onClick={confirmDeleteBot}>
                {tr("common.delete")}
              </button>
            </div>
          </div>
        </div>
      )}

      {editBotModal && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-bot-title"
        >
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h2 id="edit-bot-title" className="modal-title">
              {editBotModal.mode === "rename"
                ? tr("modal.renameBot")
                : editBotModal.mode === "persona"
                  ? tr("modal.editDirectionTitle")
                  : tr("modal.editFoaTitle")}
            </h2>
            <div className="modal-body">
              {editBotModal.mode === "rename" ? (
                <input
                  value={editBotModal.value}
                  onChange={(e) => setEditBotModal((m) => (m && m.mode === "rename" ? { ...m, value: e.target.value } : m))}
                  placeholder={tr("modal.botNamePh")}
                  autoFocus
                />
              ) : editBotModal.mode === "persona" ? (
                <textarea
                  value={editBotModal.value}
                  onChange={(e) => setEditBotModal((m) => (m && m.mode === "persona" ? { ...m, value: e.target.value } : m))}
                  placeholder={tr("modal.directionPh")}
                  rows={6}
                  autoFocus
                />
              ) : (
                <input
                  value={editBotModal.value}
                  onChange={(e) =>
                    setEditBotModal((m) => (m && m.mode === "formOfAddress" ? { ...m, value: e.target.value } : m))
                  }
                  placeholder={tr("modal.nicknamePh")}
                  autoFocus
                />
              )}
            </div>
            <div className="modal-actions">
              <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setEditBotModal(null)}>
                {tr("common.cancel")}
              </button>
              <button type="button" className="modal-btn" onClick={saveEditBot}>
                {tr("common.save")}
              </button>
            </div>
          </div>
        </div>
      )}

      {editMeModal && (
        <div
          className="modal-overlay"
          role="dialog"
          aria-modal="true"
          aria-labelledby="edit-me-title"
        >
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h2 id="edit-me-title" className="modal-title">{tr("modal.renameMeTitle")}</h2>
            <div className="modal-body">
              <input
                value={editMeModal.value}
                onChange={(e) => setEditMeModal({ mode: "rename", value: e.target.value })}
                placeholder={tr("modal.yourNamePh")}
                autoFocus
              />
            </div>
            <div className="modal-actions">
              <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setEditMeModal(null)}>
                {tr("common.cancel")}
              </button>
              <button type="button" className="modal-btn" onClick={saveRenameMe}>
                {tr("common.save")}
              </button>
            </div>
          </div>
        </div>
      )}

      {avatarModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="avatar-title">
          <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
            <h2 id="avatar-title" className="modal-title">
              {avatarModal.target === "user"
                ? tr("modal.changeAvatar")
                : tr("modal.changeAvatarBot").replace("{name}", avatarModal.botName)}
            </h2>
            <div className="modal-body">
              <div
                className={`dropzone ${avatarModal.dragging ? "dropzone-dragging" : ""} ${avatarModal.error ? "dropzone-error" : ""}`}
                onDragEnter={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setAvatarModal((m) => (m ? { ...m, dragging: true } : m));
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  setAvatarModal((m) => (m ? { ...m, dragging: false } : m));
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  const file = e.dataTransfer.files?.[0];
                  if (!file || !file.type.startsWith("image/")) {
                    setAvatarModal((m) => (m ? { ...m, dragging: false, error: tr("modal.dropzoneBadFile") } : m));
                    return;
                  }
                  readImageAsDataUrl(file, (dataUrl) =>
                    setAvatarModal((m) => (m ? { ...m, dataUrl, dragging: false, error: "" } : m))
                  );
                }}
              >
                {avatarModal.dataUrl ? (
                  <img src={avatarModal.dataUrl} alt="" className="dropzone-preview" />
                ) : (
                  <div className="dropzone-empty">
                    <div className="dropzone-title">{tr("modal.dropTitle")}</div>
                    <div className="dropzone-sub">{tr("modal.dropSub")}</div>
                    {avatarModal.error && <div className="dropzone-hint dropzone-hint-error">{avatarModal.error}</div>}
                  </div>
                )}
                <button type="button" className="dropzone-pick" onClick={triggerAvatarPick}>
                  {tr("modal.selectFile")}
                </button>
              </div>
            </div>
            <div className="modal-actions">
              <button type="button" className="modal-btn modal-btn-cancel" onClick={() => setAvatarModal(null)}>
                {tr("common.cancel")}
              </button>
              <button type="button" className="modal-btn" onClick={saveAvatarModal}>
                {tr("common.save")}
              </button>
            </div>
          </div>
        </div>
      )}

      <GomokuGameStartModal
        open={gomokuModalOpen}
        onClose={() => setGomokuModalOpen(false)}
        onConfirm={handleStartGomoku}
        botDisplayName={
          selectedBotId === "add-bot"
            ? tr("chat.roleAssistant")
            : customBots.find((b) => b.id === selectedBotId)?.name?.trim() || tr("chat.roleAssistant")
        }
        tr={tr}
      />
    </div>
  );
}

/** Create bot: backend creates session + bot row. One bot = one session. */
function AddBotView({
  token,
  botCount = 0,
  onSaved,
}: {
  token: string | null;
  botCount?: number;
  /** Called with the new bot after successful create; parent switches to chat. */
  onSaved?: (bot: Bot) => void | Promise<void>;
}) {
  const { t: tr } = useLocale();
  const [name, setName] = useState("");
  const [formOfAddress, setFormOfAddress] = useState("");
  const [primaryInterest, setPrimaryInterest] = useState<string>(DEFAULT_PRIMARY_INTEREST_KEY);
  const [secondaryInterests, setSecondaryInterests] = useState<string[]>([]);
  const [initiativeLevel, setInitiativeLevel] = useState<InitiativeLevel>("medium");
  const [gameReplyStyle, setGameReplyStyle] = useState<GameReplyStyle>(DEFAULT_GAME_REPLY_STYLE);
  const [avatarDataUrl, setAvatarDataUrl] = useState<string | null>(null);
  const [direction, setDirection] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");
  const [building, setBuilding] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [avatarDropError, setAvatarDropError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const readImageAsDataUrl = (file: File, onDone: (dataUrl: string) => void) => {
    const reader = new FileReader();
    reader.onload = () => onDone(reader.result as string);
    reader.readAsDataURL(file);
  };

  const handleAvatarChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file?.type.startsWith("image/")) return;
    setAvatarDropError("");
    readImageAsDataUrl(file, (dataUrl) => setAvatarDataUrl(dataUrl));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!token) {
      setError(tr("addBot.needLogin"));
      return;
    }
    if (botCount >= MAX_BOTS) {
      setError(tr("addBot.maxBots").replace("{n}", String(MAX_BOTS)));
      return;
    }
    setBuilding(true);
    try {
      const created = await api.createBot(
        token,
        name.trim() || "My Bot",
        direction.trim() || "a helpful, friendly companion",
        avatarDataUrl,
        formOfAddress.trim() || null,
        primaryInterest.trim() || DEFAULT_PRIMARY_INTEREST_KEY,
        secondaryInterests,
        initiativeLevel,
        gameReplyStyle
      );
      setSaved(true);
      await onSaved?.(created);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : tr("error.createBot"));
    } finally {
      setBuilding(false);
    }
  };

  return (
    <div className="add-bot-wrap">
      <h1 className="add-bot-title">{tr("addBot.title")}</h1>
      <p className="add-bot-desc">
        {tr("addBot.desc")}
      </p>
      <form onSubmit={handleSubmit} className="add-bot-form">
        <div className="add-bot-field">
          <label>{tr("addBot.botName")}</label>
          <input
            type="text"
            className="add-bot-input"
            placeholder={tr("addBot.botNamePh")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="add-bot-field">
          <label>{tr("addBot.formOfAddress")}</label>
          <input
            type="text"
            className="add-bot-input"
            placeholder={tr("addBot.formOfAddressPh")}
            value={formOfAddress}
            onChange={(e) => setFormOfAddress(e.target.value)}
          />
        </div>
        <div className="add-bot-field">
          <p className="add-bot-interests-intro">{tr("interests.intro")}</p>
          <label>{tr("profile.primaryInterest")}</label>
          <div className="interest-chip-grid" role="radiogroup" aria-label={tr("profile.primaryInterestAria")}>
            {PRIMARY_INTEREST_OPTIONS.map((o) => {
              const on = primaryInterest === o.key;
              return (
                <button
                  key={o.key}
                  type="button"
                  role="radio"
                  className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                  aria-checked={on}
                  onClick={() => {
                    setPrimaryInterest(o.key);
                    setSecondaryInterests((prev) => prev.filter((k) => k !== o.key));
                  }}
                >
                  {tr(`interest.${o.key}`)}
                </button>
              );
            })}
          </div>
        </div>
        <div className="add-bot-field">
          <label>{tr("profile.secondaryInterests")}</label>
          <div className="interest-chip-grid" role="group" aria-label={tr("profile.secondaryInterestsAria")}>
            {SECONDARY_INTEREST_OPTIONS.map((o) => {
              const on = secondaryInterests.includes(o.key);
              const disabled = (!on && secondaryInterests.length >= 3) || o.key === primaryInterest;
              return (
                <button
                  key={o.key}
                  type="button"
                  className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                  disabled={disabled}
                  onClick={() => {
                    setSecondaryInterests((prev) =>
                      prev.includes(o.key)
                        ? prev.filter((k) => k !== o.key)
                        : prev.length < 3
                          ? [...prev, o.key]
                          : prev
                    );
                  }}
                >
                  {tr(`interest.${o.key}`)}
                </button>
              );
            })}
          </div>
        </div>
        <div className="add-bot-field">
          <div className="add-bot-initiative-head">
            <label>{tr("profile.initiative")}</label>
            <span className="bot-profile-tooltip-host add-bot-initiative-help">
              <button
                type="button"
                className="bot-profile-help-trigger"
                aria-label={tr("profile.initiativeHelpAria")}
                aria-describedby="add-bot-initiative-tip"
              >
                <span aria-hidden>?</span>
              </button>
              <span id="add-bot-initiative-tip" className="bot-profile-tooltip" role="tooltip">
                {tr("initiative.tooltip")}
              </span>
            </span>
          </div>
          <div className="interest-chip-grid" role="radiogroup" aria-label={tr("profile.initiativeLevelAria")}>
            {INITIATIVE_OPTIONS.map((o) => {
              const on = initiativeLevel === o.key;
              return (
                <button
                  key={o.key}
                  type="button"
                  role="radio"
                  className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                  aria-checked={on}
                  onClick={() => setInitiativeLevel(o.key)}
                >
                  {tr(`initiative.${o.key}`)}
                </button>
              );
            })}
          </div>
        </div>
        <div className="add-bot-field">
          <div className="add-bot-initiative-head">
            <label>{tr("addBot.gameReplyStyle")}</label>
            <span className="bot-profile-tooltip-host add-bot-initiative-help">
              <button
                type="button"
                className="bot-profile-help-trigger"
                aria-label={tr("addBot.gameReplyStyleHelpAria")}
                aria-describedby="add-bot-game-reply-tip"
              >
                <span aria-hidden>?</span>
              </button>
              <span id="add-bot-game-reply-tip" className="bot-profile-tooltip" role="tooltip">
                {tr("addBot.gameReplyStyleTip")}
              </span>
            </span>
          </div>
          <div className="interest-chip-grid" role="radiogroup" aria-label={tr("profile.gameReplyStyleAria")}>
            {GAME_REPLY_STYLE_OPTIONS.map(({ key: k }) => {
              const on = gameReplyStyle === k;
              return (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  className={`interest-chip ${on ? "interest-chip-on" : ""}`}
                  aria-checked={on}
                  onClick={() => setGameReplyStyle(k)}
                >
                  {tr(`gameReplyStyle.${k}`)}
                </button>
              );
            })}
          </div>
        </div>
        <div className="add-bot-field">
          <label>{tr("addBot.avatar")}</label>
          <div
            className={`dropzone ${dragging ? "dropzone-dragging" : ""} ${avatarDropError ? "dropzone-error" : ""}`}
            onDragEnter={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setDragging(true);
            }}
            onDragOver={(e) => {
              e.preventDefault();
              e.stopPropagation();
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setDragging(false);
            }}
            onDrop={(e) => {
              e.preventDefault();
              e.stopPropagation();
              setDragging(false);
              const file = e.dataTransfer.files?.[0];
              if (!file || !file.type.startsWith("image/")) {
                setAvatarDropError(tr("modal.dropzoneBadFile"));
                return;
              }
              setAvatarDropError("");
              readImageAsDataUrl(file, (dataUrl) => setAvatarDataUrl(dataUrl));
            }}
          >
            {avatarDataUrl ? (
              <img src={avatarDataUrl} alt="" className="dropzone-preview" />
            ) : (
              <div className="dropzone-empty">
                <div className="dropzone-title">{tr("modal.dropTitle")}</div>
                <div className="dropzone-sub">{tr("modal.dropSub")}</div>
                {avatarDropError && <div className="dropzone-hint dropzone-hint-error">{avatarDropError}</div>}
              </div>
            )}
            <button type="button" className="dropzone-pick" onClick={() => fileRef.current?.click()}>
              {tr("modal.selectFile")}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept="image/*"
              onChange={handleAvatarChange}
              style={{ display: "none" }}
            />
          </div>
        </div>
        <div className="add-bot-field">
          <label>{tr("addBot.direction")}</label>
          <textarea
            className="add-bot-input"
            placeholder={tr("addBot.directionPh")}
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
            rows={3}
          />
        </div>
        {error && <p className="error">{error}</p>}
          <button type="submit" className="add-bot-submit" disabled={building}>
          {building ? tr("addBot.creating") : tr("addBot.create")}
        </button>
        {saved && <p className="add-bot-saved">{tr("addBot.saved")}</p>}
      </form>
    </div>
  );
}
