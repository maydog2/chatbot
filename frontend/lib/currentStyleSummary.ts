/**
 * Generates "Current style summary" copy from relationship metrics + bot direction.
 */

export type RelBand = "low" | "mid" | "high";

const ADJECTIVE_POOL = [
  "serious",
  "restrained",
  "sharp-tongued",
  "dry",
  "calm",
  "attentive",
  "stoic",
  "sarcastic",
  "protective",
  "gentle",
  "blunt",
  "formal",
] as const;

const MAX_TAGS = 5;

function band(n: number): RelBand {
  const x = Math.max(0, Math.min(100, Math.floor(Number(n))));
  if (x <= 39) return "low";
  if (x <= 69) return "mid";
  return "high";
}

/** Pick two base adjectives from direction text, or fall back to serious / restrained. */
export function extractBaseAdjectives(direction: string): [string, string] {
  const fallback: [string, string] = ["serious", "restrained"];
  const text = (direction || "").toLowerCase().replace(/\s+/g, " ").trim();
  if (!text) return fallback;

  const found: string[] = [];
  const used = new Set<string>();

  const sortedPool = [...ADJECTIVE_POOL].sort((a, b) => b.length - a.length);
  for (const adj of sortedPool) {
    if (found.length >= 2) break;
    const re = new RegExp(`\\b${adj.replace(/-/g, "\\-")}\\b`, "i");
    if (re.test(text) && !used.has(adj)) {
      found.push(adj);
      used.add(adj);
    }
  }

  if (found.length === 0) return fallback;
  if (found.length === 1) return [found[0], fallback[1]];
  return [found[0], found[1]];
}

/** Tag label: words separated by spaces (no hyphens joining parts). */
function tagLabelFromAdj(s: string): string {
  return s
    .split("-")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(" ");
}

function sentence1(trust: RelBand, resonance: RelBand, base1: string, base2: string): string {
  const b1 = base1;
  const b2 = base2;
  const key = `${trust}_${resonance}` as const;
  const templates: Record<string, string> = {
    low_low:
      "He comes across as {base1} and {base2}, guarded and still sizing you up; the bond feels careful, not easy yet.",
    low_mid:
      "He comes across as {base1} and {base2}, guarded but picking up your rhythm—warmth is still behind a wall.",
    low_high:
      "He comes across as {base1} and {base2}, guarded even though he reads you well; trust has not caught up to attunement.",
    mid_low:
      "He comes across as {base1} and {base2}, reserved yet willing to talk; the pace still feels a bit stiff.",
    mid_mid:
      "He comes across as {base1} and {base2}, quietly engaged; conversation is finding a steadier groove.",
    mid_high:
      "He comes across as {base1} and {base2}, attentive and in step with you, though he still holds something back.",
    high_low:
      "He comes across as {base1} and {base2}, more relaxed with you; timing together is still catching up.",
    high_mid:
      "He comes across as {base1} and {base2}, easing up—he trusts you more and the flow is getting natural.",
    high_high:
      "He comes across as {base1} and {base2}, grounded with you; rhythm and trust feel aligned.",
  };
  const t = templates[key] ?? templates.mid_mid;
  return t.replace("{base1}", b1).replace("{base2}", b2);
}

function moodSentence(mood: string): string {
  const m = (mood || "Calm").trim();
  const map: Record<string, string> = {
    Calm: "Mood: calm, steady.",
    Quiet: "Mood: quiet, inward.",
    Happy: "Mood: a little lighter.",
    Irritated: "Mood: short, on edge.",
    Playful: "Mood: teasing, looser.",
    Tired: "Mood: low energy, flat.",
  };
  return map[m] ?? map.Calm;
}

function sentence2(affection: RelBand, openness: RelBand, mood: string): string {
  const ms = moodSentence(mood);
  const key = `${affection}_${openness}` as const;
  const templates: Record<string, string> = {
    low_low: "Little warmth on the surface; inner life stays private. {mood_sentence}",
    low_mid: "Still cool in tone, but he hints at more of what he thinks. {mood_sentence}",
    low_high: "He can say what he means without much cozy warmth. {mood_sentence}",
    mid_low: "A hint of care under the reserve; feelings stay mostly inside. {mood_sentence}",
    mid_mid: "Soft warmth shows; he is opening up a little. {mood_sentence}",
    mid_high: "Warmth reads clearly when it matters; he shares more willingly. {mood_sentence}",
    high_low: "Care runs deep but shows indirectly, not in big speeches. {mood_sentence}",
    high_mid: "Clearly warm, still understated—less hiding than before. {mood_sentence}",
    high_high: "Warm and open; more of his inner world is on the table. {mood_sentence}",
  };
  const t = templates[key] ?? templates.mid_mid;
  return t.replace("{mood_sentence}", ms);
}

function trustTag(b: RelBand): string {
  if (b === "low") return "Guarded";
  if (b === "mid") return "Reserved";
  return "Trusting";
}

function resonanceTag(b: RelBand): string {
  if (b === "low") return "Adjusting";
  if (b === "mid") return "Settling";
  return "In sync";
}

export type CurrentStyleSummaryResult = {
  paragraph: string;
  tags: string[];
};

export function generateCurrentStyleSummary(input: {
  trust: number;
  resonance: number;
  affection: number;
  openness: number;
  mood: string;
  direction: string;
}): CurrentStyleSummaryResult {
  const tb = band(input.trust);
  const rb = band(input.resonance);
  const ab = band(input.affection);
  const ob = band(input.openness);
  const [raw1, raw2] = extractBaseAdjectives(input.direction);
  const b1 = tagLabelFromAdj(raw1);
  const b2 = tagLabelFromAdj(raw2);

  const s1 = sentence1(tb, rb, b1.toLowerCase(), b2.toLowerCase());
  const s2 = sentence2(ab, ob, input.mood);
  const paragraph = `${s1} ${s2}`;

  const tags: string[] = [b1, b2, trustTag(tb), resonanceTag(rb)];
  const moodTrim = (input.mood || "").trim();
  if (moodTrim && tags.length < MAX_TAGS) tags.push(moodTrim);

  return { paragraph, tags: tags.slice(0, MAX_TAGS) };
}
