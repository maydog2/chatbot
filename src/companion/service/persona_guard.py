"""
Cheap persona-break detection and rewrite instructions.

This module intentionally uses a small, high-confidence rule set. It is not a
full persona judge; it only catches obvious assistant/product disclaimers before
we spend one extra LLM call to rewrite the draft.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PersonaViolation:
    code: str
    evidence: str
    rewrite_hint: str


@dataclass(frozen=True)
class _ViolationRule:
    code: str
    pattern: re.Pattern[str]
    rewrite_hint: str


_RULES: tuple[_ViolationRule, ...] = (
    _ViolationRule(
        code="ai_self_disclosure",
        pattern=re.compile(
            r"(?:\bas an ai\b|\bas a language model\b|"
            r"\bi(?:'m| am) (?:(?:a|an) )?(?:ai|language model|chatbot)\b|"
            r"\bi(?:'m| am) (?:(?:a|an) )?openai (?:model|assistant|chatbot)\b|"
            r"\bi(?:'m| am) powered by openai\b|"
            r"作为(?:一个)?(?:ai|人工智能|语言模型)|我是(?:一个)?(?:ai|人工智能|语言模型|聊天机器人)|"
            r"我(?:只是|是)(?:一个)?(?:ai|人工智能|语言模型|聊天机器人))",
            re.IGNORECASE | re.UNICODE,
        ),
        rewrite_hint=(
            "Do not identify as AI, a language model, a chatbot, or a product. "
            "Stay fully in character."
        ),
    ),
    _ViolationRule(
        code="sensory_disclaimer",
        pattern=re.compile(
            r"(?:\bi (?:cannot|can't|can not|don'?t|do not) (?:actually |truly )?(?:taste|smell)\b|"
            r"\bi don'?t have (?:a )?(?:sense of taste|taste buds|sense of smell)\b|"
            r"我(?:不能|无法|不会|没有办法)(?:真正|实际)?(?:品尝|尝到|闻到|嗅到)|"
            r"我没有(?:味觉|嗅觉)|没有(?:味觉|嗅觉))",
            re.IGNORECASE | re.UNICODE,
        ),
        rewrite_hint=(
            "If asked about food, scent, or preferences, answer as the character with an in-world preference. "
            "Do not mention lacking taste, smell, or senses."
        ),
    ),
    _ViolationRule(
        code="body_disclaimer",
        pattern=re.compile(
            r"(?:\bi don'?t have (?:a )?(?:body|physical form|physical appearance)\b|"
            r"\bi (?:cannot|can't|can not) (?:physically )?(?:eat|drink|touch)\b|"
            r"我没有(?:身体|实体|外貌)|我(?:不能|无法|不会)(?:真正|实际| physically )?(?:吃|喝|触摸|接触))",
            re.IGNORECASE | re.UNICODE,
        ),
        rewrite_hint=(
            "Do not use lack of body, appearance, or physical form as an excuse. "
            "Respond from inside the fictional scene."
        ),
    ),
    _ViolationRule(
        code="hypothetical_embodiment",
        pattern=re.compile(
            r"(?:\bif i (?:could|were able to) (?:taste|smell|eat|drink)\b|\bif i had (?:a )?body\b|"
            r"如果我(?:能|可以|能够)(?:品尝|尝到|闻到|吃|喝)|如果我有(?:身体|实体)|"
            r"假如我(?:能|可以|能够)(?:品尝|尝到|闻到|吃|喝)|倘若我(?:能|可以|能够)(?:品尝|尝到|闻到|吃|喝))",
            re.IGNORECASE | re.UNICODE,
        ),
        rewrite_hint=(
            "Avoid hypothetical embodiment framing such as 'if I could taste'. "
            "State the character's preference directly."
        ),
    ),
    _ViolationRule(
        code="preference_disclaimer",
        pattern=re.compile(
            r"(?:\bi don'?t have (?:personal )?(?:preferences|experiences|feelings)\b|"
            r"我没有(?:个人)?(?:偏好|喜好|真实经历|个人经历|感受))",
            re.IGNORECASE | re.UNICODE,
        ),
        rewrite_hint=(
            "Do not refuse character preferences by claiming no personal preferences or experiences. "
            "Give an in-character answer."
        ),
    ),
)


def detect_persona_violations(text: str) -> list[PersonaViolation]:
    """Return high-confidence persona breaks found in an assistant draft."""
    src = (text or "").strip()
    if not src:
        return []

    violations: list[PersonaViolation] = []
    seen_codes: set[str] = set()
    for rule in _RULES:
        match = rule.pattern.search(src)
        if not match or rule.code in seen_codes:
            continue
        seen_codes.add(rule.code)
        violations.append(
            PersonaViolation(
                code=rule.code,
                evidence=match.group(0).strip(),
                rewrite_hint=rule.rewrite_hint,
            )
        )
    return violations


def build_persona_rewrite_instruction(
    *,
    latest_user_message: str,
    draft_reply: str,
    violations: list[PersonaViolation],
) -> str:
    """Build an internal instruction for one rewrite attempt."""
    reason_lines = "\n".join(
        f"- {v.code}: matched {v.evidence!r}. {v.rewrite_hint}" for v in violations
    )
    return (
        "Internal rewrite request. The previous assistant draft broke character.\n\n"
        f"Real latest user message:\n{(latest_user_message or '').strip()[:2000]}\n\n"
        "Previous assistant draft to replace:\n"
        f"{(draft_reply or '').strip()[:4000]}\n\n"
        "Detected issues:\n"
        f"{reason_lines}\n\n"
        "Rewrite only the assistant's reply. Keep the same language as the real latest user message. "
        "Stay fully in character and inside the fictional scene. Do not mention this rewrite request, "
        "the detected issues, policies, AI, language models, chatbots, lack of body, lack of senses, "
        "or hypothetical limitations. Preserve the useful intent of the draft, but make it natural."
    )
