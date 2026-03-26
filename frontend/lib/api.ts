const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_at: string;
};

export type Message = {
  id: number;
  user_id: number;
  session_id: number;
  role: string;
  content: string;
  created_at: string;
};

export type Relationship = {
  trust: number;
  resonance: number;
  affection: number;
  openness: number;
  mood: string;
  display_name: string;
};

export type Me = { display_name: string; avatar_data_url: string | null };

export type BotInitiative = "low" | "medium" | "high";

/** Returned when POST /chat/send-bot-message includes include_initiative_debug: true */
export type InitiativeDebug = {
  base: BotInitiative;
  score: number;
  band: "very_low" | "low" | "moderate" | "high" | "very_high";
  interest_match: boolean;
  recent_user_messages: string[];
  total_turns_in_window: number;
};

export type Bot = {
  id: number;
  user_id: number;
  session_id: number;
  name: string;
  system_prompt: string;
  avatar_data_url: string | null;
  direction: string | null;
  form_of_address: string | null;
  primary_interest: string | null;
  secondary_interests: string[];
  initiative: BotInitiative;
  created_at: string;
};

async function request<T>(
  path: string,
  options: RequestInit & { token?: string | null; json?: object } = {}
): Promise<T> {
  const { token, json, ...init } = options;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const body = json !== undefined ? JSON.stringify(json) : init.body;
  const res = await fetch(`${API_BASE}${path}`, { ...init, headers, body });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error((err as { detail?: string }).detail ?? "Request failed");
  }
  return res.json() as Promise<T>;
}

export const api = {
  register: (display_name: string, username: string, password: string) =>
    request<{ user_id: number }>("/users/register", {
      method: "POST",
      json: { display_name, username, password },
    }),

  login: (username: string, password: string, remember_me = true) =>
    request<LoginResponse>("/users/login", {
      method: "POST",
      json: { username, password, remember_me },
    }),

  logout: (token: string) =>
    request<{ revoked: boolean }>("/users/logout", {
      method: "POST",
      token,
    }),

  me: (token: string) => request<Me>("/users/me", { method: "GET", token }),

  updateMe: (token: string, patch: Partial<Pick<Me, "display_name" | "avatar_data_url">>) =>
    request<Me>("/users/me", { method: "PATCH", token, json: patch }),

  /** Message history for the given bot (each bot has its own session). */
  historyBot: (token: string, bot_id: number, limit = 50) =>
    request<{ messages: Message[] }>("/chat/history/bot", {
      method: "POST",
      token,
      json: { bot_id, limit },
    }),

  /** Send message to a bot; saves to DB and returns assistant reply + updated relationship metrics. */
  sendBotMessage: (
    token: string,
    bot_id: number,
    content: string,
    system_prompt: string,
    trust_delta = 0,
    resonance_delta = 0,
    include_initiative_debug = false
  ) =>
    request<{
      session_id: number;
      message_id: number;
      assistant_message_id?: number;
      assistant_reply: string;
      trust: number;
      resonance: number;
      affection: number;
      openness: number;
      mood: string;
      display_name: string;
      initiative_debug?: InitiativeDebug;
    }>("/chat/send-bot-message", {
      method: "POST",
      token,
      json: {
        bot_id,
        content,
        system_prompt,
        trust_delta,
        resonance_delta,
        include_initiative_debug,
      },
    }),

  /** List all bots for the current user (from DB). */
  listBots: (token: string) =>
    request<{ bots: Bot[] }>("/bots", { method: "GET", token }),

  /** Create bot: build prompt, create session, create bot. One bot = one session. */
  createBot: (
    token: string,
    name: string,
    direction: string,
    avatar_data_url: string | null = null,
    form_of_address: string | null = null,
    primary_interest: string,
    secondary_interests: string[] = [],
    initiative: BotInitiative = "medium"
  ) => {
    const p = primary_interest.trim();
    if (!p) throw new Error("Primary interest is required.");
    const json: Record<string, unknown> = {
      name,
      direction,
      avatar_data_url,
      primary_interest: p,
      secondary_interests,
      initiative,
    };
    const foa = (form_of_address ?? "").trim();
    if (foa) json.form_of_address = foa;
    return request<Bot>("/bots", { method: "POST", token, json });
  },

  /** Update bot fields (rename / edit persona). */
  updateBot: (
    token: string,
    bot_id: number,
    patch: Partial<
      Pick<
        Bot,
        | "name"
        | "direction"
        | "avatar_data_url"
        | "form_of_address"
        | "primary_interest"
        | "secondary_interests"
        | "initiative"
      >
    >
  ) =>
    request<Bot>(`/bots/${bot_id}`, {
      method: "PATCH",
      token,
      json: patch,
    }),

  /** Delete bot and its session (messages CASCADE). */
  deleteBot: (token: string, bot_id: number) =>
    request<{ deleted: boolean }>(`/bots/${bot_id}`, { method: "DELETE", token }),

  endSession: (token: string) =>
    request<{ ended: boolean }>("/chat/end", { method: "POST", token }),

  relationship: (token: string, bot_id: number) =>
    request<Relationship>(`/bots/${bot_id}/relationship`, { method: "GET", token }),

  buildPrompt: (token: string, direction: string) =>
    request<{ system_prompt: string }>("/chat/build-prompt", {
      method: "POST",
      token,
      json: { direction },
    }),

  reply: (token: string, messages: Array<{ role: string; content: string }>, system_prompt: string) =>
    request<{ assistant_reply: string }>("/chat/reply", {
      method: "POST",
      token,
      json: { messages, system_prompt },
    }),
};
