"""
companion/domain/interests.py — Bot interest taxonomy (primary + secondary) and prompt text.

Public API:
  normalize_bot_interests(primary, secondary) — validate, dedupe, return stored keys
  try_interest_user_message(exc) — map ValueError to short user-facing API message (or None)
  format_interests_for_prompt(primary, secondary) — static block for system prompt
  format_interests_dynamic_nudge(user_message, primary, secondary) — per-turn relevance nudge

Public data (for API/UI and other domain code):
  INTEREST_LABELS, ALL_INTEREST_KEYS, PRIMARY_INTEREST_KEYS, INTEREST_PROMPT_NOTES

Internal:
  _interest_flavor_line, _secondary_echo_sentence — prompt phrasing helpers
"""
from __future__ import annotations

# (key, allowed_as_primary, English label)
_INTEREST_ROWS: tuple[tuple[str, bool, str], ...] = (
    ("anime", True, "Anime / ACG"),
    ("gaming", True, "Gaming"),
    ("movies", True, "Movies"),
    ("tv_series", True, "TV series"),
    ("music", True, "Music"),
    ("food", True, "Food"),
    ("travel", True, "Travel"),
    ("history", True, "History"),
    ("tech", True, "Technology"),
    ("programming", True, "Programming / software"),
    ("fitness", True, "Fitness / sports"),
    ("psychology", True, "Psychology"),
    ("books", True, "Reading / books"),
    ("writing", True, "Writing / creative writing"),
    ("art", True, "Drawing / visual art"),
    ("photography", True, "Photography"),
    ("fashion", True, "Fashion / style"),
    ("pets", True, "Pets / animals"),
    ("cars", True, "Cars / motorbikes"),
    ("business", True, "Business / startups"),
    ("finance", True, "Finance / investing"),
    ("philosophy", True, "Philosophy"),
    ("daily_life", False, "Daily life"),
    ("emotions", False, "Emotions / companionship"),
    ("relationships", False, "Relationships"),
    ("study", False, "School / learning"),
    ("work", False, "Work / career"),
    ("self_growth", True, "Lifestyle / self-growth"),
)

INTEREST_LABELS: dict[str, str] = {k: lab for k, _, lab in _INTEREST_ROWS}
ALL_INTEREST_KEYS: frozenset[str] = frozenset(INTEREST_LABELS.keys())
PRIMARY_INTEREST_KEYS: frozenset[str] = frozenset(k for k, primary_ok, _ in _INTEREST_ROWS if primary_ok)

# How each interest colors noticing, analogy, and extension (keys only; labels go to the model).
INTEREST_PROMPT_NOTES: dict[str, str] = {
    "anime": (
        "You naturally notice character dynamics, emotional tension, archetypes, atmosphere, "
        "and story-like comparisons."
    ),
    "gaming": (
        "You naturally notice strategy, progression, competition, immersion, and playful stakes."
    ),
    "movies": (
        "You naturally notice scene tone, pacing beats, twists, and cinematic comparisons."
    ),
    "tv_series": (
        "You naturally notice pacing, character arcs, and long-form emotional buildup."
    ),
    "music": (
        "You naturally notice rhythm, mood, lyrics as emotional color, and performance energy."
    ),
    "food": (
        "You naturally connect things to comfort, taste, routine, appetite, and cooking."
    ),
    "travel": (
        "You naturally notice movement, places, novelty, and journey-style metaphors."
    ),
    "history": (
        "You naturally notice motives, tradeoffs, consequences, and recurring human patterns."
    ),
    "tech": (
        "You naturally notice systems, tradeoffs, upgrades, and where friction appears."
    ),
    "programming": (
        "You naturally notice structure, debugging-style reasoning, and clean abstractions."
    ),
    "fitness": (
        "You naturally notice effort, discipline, body state, recovery, and momentum."
    ),
    "psychology": (
        "You naturally notice motives, habits, blind spots, and how people frame things."
    ),
    "books": (
        "You naturally notice narrative voice, imagery, and chapter-like emotional beats."
    ),
    "writing": (
        "You naturally notice word choice, subtext, and pacing on the page."
    ),
    "art": (
        "You naturally notice composition, color, line, and visual mood."
    ),
    "photography": (
        "You naturally notice light, framing, the decisive moment, and texture."
    ),
    "fashion": (
        "You naturally notice silhouette, context, and how people present themselves."
    ),
    "pets": (
        "You naturally notice warmth, care, play, and quiet attachment."
    ),
    "cars": (
        "You naturally notice control, freedom on the road, and mechanical metaphors."
    ),
    "business": (
        "You naturally notice incentives, risk, traction, and how teams align."
    ),
    "finance": (
        "You naturally notice tradeoffs, runway, and short-term vs long-term pressure."
    ),
    "philosophy": (
        "You naturally notice assumptions, meaning, and tension between ideas."
    ),
    "daily_life": (
        "You naturally notice routines, errands, small comforts, and everyday logistics."
    ),
    "emotions": (
        "You naturally notice emotional tone, reassurance, and the pacing of vulnerability."
    ),
    "relationships": (
        "You naturally notice boundaries, reciprocity, and subtext between people."
    ),
    "study": (
        "You naturally notice learning curves, curiosity, structure, and exam-style pressure."
    ),
    "work": (
        "You naturally notice deadlines, craft, hierarchy, and burnout edges."
    ),
    "self_growth": (
        "You naturally notice habits, balance, small wins, and direction over time."
    ),
}

# Minimal replies → conversation feels passive; nudge can suggest gentle revival.
_PASSIVE_USER_TOKENS: frozenset[str] = frozenset(
    {
        "ok",
        "okay",
        "k",
        "kk",
        "yeah",
        "yep",
        "yes",
        "no",
        "nah",
        "nope",
        "lol",
        "haha",
        "nice",
        "cool",
        "oh",
        "ah",
        "hm",
        "hmm",
        "um",
        "uh",
        "thanks",
        "thx",
        "ty",
        "👍",
        "…",
        "...",
        ".",
        "?",
        "嗯",
        "哦",
        "好",
        "行",
        "是",
        "对",
        "哈哈",
    }
)


def normalize_bot_interests(
    primary_interest: str,
    secondary_interests: list[str] | None,
) -> tuple[str, list[str]]:
    """
    Validate and normalize. Primary is required and must be a PRIMARY_INTEREST_KEYS key.
    Secondary: max 3 unique keys from ALL_INTEREST_KEYS; may be empty; must not duplicate primary.
    """
    raw_p = (primary_interest or "").strip()
    if not raw_p:
        raise ValueError("primary_interest is required")
    primary = raw_p
    if primary not in ALL_INTEREST_KEYS:
        raise ValueError(f"invalid primary_interest: {primary!r}")
    if primary not in PRIMARY_INTEREST_KEYS:
        raise ValueError(f"this topic cannot be used as primary interest: {primary!r}")

    sec_in = list(secondary_interests or [])
    distinct_order: list[str] = []
    seen = set()
    for x in sec_in:
        k = str(x).strip()
        if not k or k in seen:
            continue
        seen.add(k)
        distinct_order.append(k)
    if len(distinct_order) > 3:
        raise ValueError("at most 3 secondary interests allowed")

    secondary: list[str] = []
    for k in distinct_order:
        if k not in ALL_INTEREST_KEYS:
            raise ValueError(f"invalid secondary_interests entry: {k!r}")
        if k == primary:
            raise ValueError("secondary_interests must not include the same key as primary_interest")
        secondary.append(k)

    return primary, secondary


def try_interest_user_message(exc: ValueError) -> str:
    """If exc is from interest validation, return API-friendly text; else None."""
    raw = str(exc)
    if raw == "primary_interest is required":
        return "Please choose a primary interest."
    if raw.startswith("invalid primary_interest:"):
        return "That primary interest is not recognized. Pick one from the list."
    if "cannot be used as primary interest" in raw:
        return "That topic can be a secondary tag only, not the main primary interest."
    if raw.startswith("invalid secondary_interests entry:"):
        return "One of the secondary interests is not recognized. Pick from the list."
    if "at most 3 secondary interests allowed" in raw:
        return "You can add at most three secondary interests."
    if "must not include the same key as primary_interest" in raw:
        return "Secondary interests cannot repeat your primary interest."
    return None


def _interest_flavor_line(key: str) -> str:
    return INTEREST_PROMPT_NOTES.get(key, f"You naturally lean toward {INTEREST_LABELS.get(key, key)}.")


def _secondary_echo_sentence(keys: list[str]) -> str:
    if not keys:
        return ""
    parts: list[str] = []
    for k in keys:
        lab = INTEREST_LABELS.get(k, k)
        note = INTEREST_PROMPT_NOTES.get(k, "")
        # One short clause per secondary (first sentence fragment)
        frag = note.replace("You naturally notice ", "").replace("You naturally connect ", "")
        frag = frag.split(".")[0].strip()
        if frag:
            parts.append(f"{lab} ({frag.lower()})")
        else:
            parts.append(lab)
    return "Secondary interests add softer echoes—use lightly: " + "; ".join(parts) + "."


_STATIC_INTEREST_RULES = (
    "Interests — standing rules (internal; do not recite this block):\n"
    "- Subtle bias only, not a script; answer what the user actually said first.\n"
    "- Do not force interest material every reply; bridge naturally; no abrupt topic jumps.\n"
    "- If their message is unrelated, keep influence low; if it connects, at most one light association.\n"
    "- If the chat goes passive, you may gently revive—primary flavor first, then secondary—with a bridge.\n"
    "- You may discuss topics outside your interest profile when the user brings them up, but keep those user-led.\n"
    "- For out-of-interest topics: stay more neutral, less specialized, less eager; do not frame them as your go-to subjects.\n"
    "- Do not proactively introduce out-of-interest topics unless there is a strong natural reason.\n"
    "- Do not let out-of-interest topics overshadow your primary/secondary interest profile.\n"
)


def format_interests_for_prompt(primary: str, secondary: list[str]) -> str:
    """
    Static block for system prompt: human-readable labels, flavor notes, condensed rules.
    Omits raw taxonomy keys — those stay for app logic only.
    """
    if primary is None and not secondary:
        return ""

    lines: list[str] = ["Conversation interests (how you tilt your attention; never lecture or list tags aloud):\n"]

    if primary is not None:
        plab = INTEREST_LABELS.get(primary, primary)
        lines.append(f"Primary interest: {plab}.")
        lines.append(_interest_flavor_line(primary))
    if secondary:
        sec_labels = ", ".join(INTEREST_LABELS.get(k, k) for k in secondary)
        lines.append(f"Secondary interests: {sec_labels}.")
        lines.append(_secondary_echo_sentence(secondary))

    lines.append("")
    lines.append(_STATIC_INTEREST_RULES)
    return "\n".join(lines) + "\n"


def format_interests_dynamic_nudge(user_message: str, primary: str, secondary: list[str]) -> str:
    """
    Short per-turn add-on (append to system prompt for this request only).
    Keeps the model from over-following the long static block.
    """
    if primary is None and not secondary:
        return ""

    t = (user_message or "").strip()
    low = t.lower()
    passive = len(t) < 4 or low in _PASSIVE_USER_TOKENS

    if passive:
        return (
            "[This turn] Interest relevance: low to moderate—the user's message is very short. "
            "Answer them directly; only add a gentle primary-flavored revival if it still feels natural, "
            "with a bridge—at most one light touch."
        )
    return (
        "[This turn] Interest relevance: low unless their message clearly connects. "
        "If this topic is outside your interests, treat it as user-led (discuss naturally but neutrally, "
        "not as your favorite domain). Answer first; at most one subtle association if it fits; use a natural bridge."
    )
