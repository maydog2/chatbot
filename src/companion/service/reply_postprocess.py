"""
Deterministic, low-risk post-processing of model replies (no LLM calls).

Persona-breaking semantic issues, such as AI self-disclosure or sensory/body
disclaimers, belong in persona_guard.py where they can trigger one rewrite.
This module only keeps mechanical style cleanup that is safe to apply directly.
"""
from __future__ import annotations

import re

# Trailing questions that turn the topic back to the user (initiative / assistant tone).
_CLOSING_QUESTION_BOUNCE = re.compile(
    r"(需要我|帮你|协助您|帮您|为你效劳|有什么需要|能为你|我能帮|how can I help|what can I do|"
    r"你呢|你也是|你最近|你有什么|你.*钟爱|你.*喜欢.*吗|tell me (what|about)|what about you|how about you|"
    r"your favorite|anything else)",
    re.IGNORECASE | re.UNICODE,
)


def enforce_low_activity_reply_style(text: str, mood: str) -> str:
    """Deterministic post-process for Irritated/Tired to avoid proactive topic throwing."""
    m = (mood or "").strip()
    if m not in {"Irritated", "Tired"}:
        return text
    src = (text or "").strip()
    if not src:
        return src

    parts = [p.strip() for p in re.findall(r"[^。！？!?.\n]+[。！？!?.]?", src) if p.strip()]
    if not parts:
        parts = [src]

    max_sentences = 3 if m == "Irritated" else 2
    question_limit = 1 if m == "Irritated" else 0
    kept: list[str] = []
    q_used = 0
    for p in parts:
        is_q = ("?" in p) or ("？" in p)
        if is_q and q_used >= question_limit:
            continue
        if (
            re.search(
                r"(你呢|你最近|还有什么|想聊|感兴趣|想说说|"
                r"what about you|how about you|anything else|want to talk|interested in|tell me about)",
                p,
                re.IGNORECASE,
            )
            and is_q
        ):
            continue
        kept.append(p)
        if is_q:
            q_used += 1
        if len(kept) >= max_sentences:
            break

    if not kept:
        first = parts[0]
        first = first.replace("？", "。").replace("?", ".")
        kept = [first]

    out = "".join(kept).strip()
    if m == "Tired":
        out = out.replace("？", "。").replace("?", ".")
    return out


def is_irritated_probe(user_text: str) -> bool:
    txt = (user_text or "").strip().lower()
    if not txt:
        return False
    zh_hits = ("生气", "不爽", "恼火", "火大", "气了")
    en_hits = ("are you angry", "are you mad", "you mad", "why angry", "upset")
    return any(k in txt for k in zh_hits) or any(k in txt for k in en_hits)


def enforce_irritated_probe_admission(
    text: str, *, mood: str, user_text: str, form_of_address: str
) -> str:
    """When directly asked about anger in Irritated mood, avoid flat denial."""
    if (mood or "").strip() != "Irritated":
        return text
    if not is_irritated_probe(user_text):
        return text
    src = (text or "").strip()
    if not src:
        return src
    deny_patterns = (
        r"不生气",
        r"没生气",
        r"不会因为.*生气",
        r"i[' ]?m not angry",
        r"not angry",
    )
    if any(re.search(p, src, re.IGNORECASE) for p in deny_patterns):
        who = (form_of_address or "").strip()
        prefix = f"{who}，" if who else ""
        return f"{prefix}有点不爽，但还在说正事。"
    return src


def enforce_irritated_tone_floor(text: str, mood: str) -> str:
    """Remove overly warm/service-style phrases when mood is Irritated."""
    if (mood or "").strip() != "Irritated":
        return text
    out = (text or "").strip()
    if not out:
        return out
    replacements = (
        (r"我还是乐意帮忙。?", "先把重点说清。"),
        (r"随时告诉我。?", "有事就直说。"),
        (r"我在这里陪着你。?", "我在。"),
        (r"很乐意参与。?", "可以谈，但别绕。"),
        (r"如果有其他话题想讨论.*", "要么继续这个，要么换个有价值的点。"),
        (r"i(?:'m| am) (?:still )?(?:happy|glad) to help\.?", "Get to the point."),
        (r"let me know (?:anytime|if you need anything)\.?", "Say it directly."),
        (r"i(?:'m| am) here for you\.?", "I'm here."),
        (r"happy to discuss(?: this)?\.?", "We can discuss it, but don't drag it out."),
        (r"if you (?:have|want to discuss) (?:any )?other topics?.*", "Continue this, or bring up something worthwhile."),
    )
    for pat, repl in replacements:
        out = re.sub(pat, repl, out, flags=re.IGNORECASE)
    return out.strip()


def enforce_initiative_closing_question(text: str, band: str) -> str:
    """
    For low effective initiative, drop trailing sentence(s) that match service-style or
    bounce-back questions (model often still adds them despite prompt).
    """
    b = (band or "").strip()
    if b not in {"very_low", "low"}:
        return text
    src = (text or "").strip()
    if not src:
        return src

    parts = [p.strip() for p in re.findall(r"[^。！？!?.\n]+[。！？!?.]?", src) if p.strip()]
    if not parts:
        return src

    def is_question_chunk(p: str) -> bool:
        return "?" in p or "？" in p

    while parts and is_question_chunk(parts[-1]) and _CLOSING_QUESTION_BOUNCE.search(parts[-1]):
        parts.pop()

    if not parts:
        return src

    return "".join(parts).strip()
