"""
companion/service/reply_postprocess.py — Deterministic post-processing of model replies (no LLM calls).

Public API (imported by service.__init__; some names also aliased as service._strip_* for tests):
  strip_roleplay_sensory_disclaimers — remove assistant-style taste / imagination openers
  enforce_initiative_closing_question — strip service-style closing questions when initiative band is low
  enforce_low_activity_reply_style — shorten / limit questions for Irritated or Tired mood
  is_irritated_probe — detect user asking if bot is angry/upset
  enforce_irritated_probe_admission — avoid flat denial when probed in Irritated mood
  enforce_irritated_tone_floor — replace overly warm phrases when Irritated

Internal:
  _strip_sensory_meta_sentences — drop whole sentences matching sensory-meta regex
"""
from __future__ import annotations

import re

# Opening lines that read as "AI assistant" rather than in-scene character (model often ignores prompt).
_SENSORY_DISCLAIMER_PATTERNS: tuple[tuple[str, int], ...] = (
    (r"^虽然不能[^，。]{0,56}品尝[^，。]{0,32}，(?:但)?\s*", re.IGNORECASE | re.UNICODE),
    (r"^虽说[^，。]{0,24}不能[^，。]{0,16}品尝[^，。]{0,24}，(?:但)?\s*", re.UNICODE),
    (r"^虽然[^，。]{0,24}无法[^，。]{0,24}真正?品尝[^，。]{0,40}，(?:但)?(?:在想象中，?)?\s*", re.UNICODE),
    (r"^无法品尝，(?:但)?\s*", re.UNICODE),
    (r"^我(?:并)?不能(?:实际)?品尝[^，。]{0,24}，(?:但)?\s*", re.UNICODE),
    (r"^如果能品尝，?\s*", re.UNICODE),
    (r"^假使能品尝，?\s*", re.UNICODE),
    (r"^倘若能品尝，?\s*", re.UNICODE),
    (r"^在想象中，?\s*", re.UNICODE),
    (r"^Although I cannot (?:actually |truly )?taste[^,]{0,80},?\s*(?:but\s+)?(?:in my imagination,?\s*)?", re.IGNORECASE),
    (r"^I (?:can)?not (?:actually |truly )?taste(?: food)?,?\s*(?:but\s+)?(?:in my imagination,?\s*)?", re.IGNORECASE),
    (r"^If I could taste,?\s*", re.IGNORECASE),
    (r"^If I were able to taste,?\s*", re.IGNORECASE),
)

# Whole sentences that stay in the "AI has no senses / only imagination" frame.
_SENSORY_META_SENTENCE = re.compile(
    r"(味觉遐想|无限的味觉|在想象中(?:引发|也能|总能|.*味觉)|"
    r"美食的多样性.*(?:着迷|遐想)|complex flavors.*fascinating.*imagination)",
    re.IGNORECASE | re.UNICODE,
)

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

    parts = [p.strip() for p in re.findall(r"[^。！？!?\n]+[。！？!?]?", src) if p.strip()]
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
        if re.search(r"(你呢|你最近|还有什么|想聊|感兴趣|想说说)", p) and is_q:
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
    )
    for pat, repl in replacements:
        out = re.sub(pat, repl, out)
    return out.strip()


def _strip_sensory_meta_sentences(text: str) -> str:
    """Drop sentences that revolve around imagined taste / AI sensory disclaimers."""
    src = (text or "").strip()
    if not src:
        return src
    parts = [p.strip() for p in re.findall(r"[^。！？!?\n]+[。！？!?]?", src) if p.strip()]
    if not parts:
        return src
    kept = [p for p in parts if not _SENSORY_META_SENTENCE.search(p)]
    if not kept:
        return src
    return "".join(kept).strip()


def strip_roleplay_sensory_disclaimers(text: str) -> str:
    """Remove common assistant-style sensory disclaimers from the start of a reply."""
    s = (text or "").strip()
    if not s:
        return s
    prev = None
    while prev != s:
        prev = s
        for pat, flags in _SENSORY_DISCLAIMER_PATTERNS:
            s = re.sub(pat, "", s, flags=flags).lstrip()
    s = re.sub(r"^但\s*", "", s)
    s = re.sub(r"^我可能会对", "我对", s)
    s = re.sub(r"^我也许会", "我", s)
    s = s.strip()
    return _strip_sensory_meta_sentences(s)


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

    parts = [p.strip() for p in re.findall(r"[^。！？!?\n]+[。！？!?]?", src) if p.strip()]
    if not parts:
        return src

    def is_question_chunk(p: str) -> bool:
        return "?" in p or "？" in p

    while parts and is_question_chunk(parts[-1]) and _CLOSING_QUESTION_BOUNCE.search(parts[-1]):
        parts.pop()

    if not parts:
        return src

    return "".join(parts).strip()
