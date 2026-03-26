export type InitiativeLevel = "low" | "medium" | "high";

export const INITIATIVE_OPTIONS: { key: InitiativeLevel; label: string }[] = [
  { key: "low", label: "Low" },
  { key: "medium", label: "Medium" },
  { key: "high", label: "High" },
];

/** Tooltip for create-bot + profile (matches product copy). */
export const INITIATIVE_TOOLTIP =
  "How likely the bot is to lead, extend, or reopen conversation on its own, may shift slightly with mood and context.";

export function normalizeInitiativeLevel(raw: string | null | undefined): InitiativeLevel {
  const k = (raw ?? "medium").toLowerCase().trim();
  if (k === "low" || k === "medium" || k === "high") return k;
  return "medium";
}

export function initiativeLabel(key: InitiativeLevel): string {
  return INITIATIVE_OPTIONS.find((o) => o.key === key)?.label ?? key;
}
