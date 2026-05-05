"""
Background memory extraction pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import math
import os
import re
from typing import Any

import psycopg

from companion.infra import db, llm

logger = logging.getLogger(__name__)

_ALLOWED_MEMORY_TYPES = {"preference", "goal", "background", "instruction"}
_DEFAULT_RECENT_CONTEXT_LIMIT = 10
_DEFAULT_PROMPT_MEMORY_LIMIT = 8
_DEFAULT_PROMPT_MEMORY_LINE_CHAR_LIMIT = 240
_DEFAULT_DEDUPE_SIMILARITY_THRESHOLD = 0.88
_ACTIVE_MEMORY_LIMIT = 100
_TOTAL_MEMORY_LIMIT = 1000


def _memory_debug_enabled() -> bool:
    return os.getenv("CHATBOT_LOG_MEMORY", "").strip().lower() in {"1", "true", "yes", "on"}


def _memory_preview(content: str, *, limit: int = 160) -> str:
    content = re.sub(r"\s+", " ", str(content or "").strip())
    if len(content) <= limit:
        return content
    return content[: limit - 3] + "..."


def _memory_debug(message: str, *args: object) -> None:
    if _memory_debug_enabled():
        logger.info("memory " + message, *args)


@dataclass(frozen=True)
class MemoryCandidate:
    content: str
    memory_type: str
    importance: int = 50
    evidence: str = ""


def _strip_json_fence(raw: str) -> str:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```\s*$", "", raw)
    return raw.strip()


def parse_memory_candidates(raw: str) -> list[MemoryCandidate]:
    raw = _strip_json_fence(raw)
    if not raw:
        return []
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("parse_memory_candidates: invalid JSON from extractor: %r", raw[:500])
        return []
    if not isinstance(obj, dict):
        return []
    items = obj.get("memories")
    if not isinstance(items, list):
        return []

    candidates: list[MemoryCandidate] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        memory_type = str(item.get("memory_type") or "").strip()
        if not content or memory_type not in _ALLOWED_MEMORY_TYPES:
            continue
        try:
            importance = int(item.get("importance", 50))
        except (TypeError, ValueError):
            importance = 50
        importance = max(0, min(100, importance))
        normalized = normalize_memory_content(content)
        if normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(
            MemoryCandidate(
                content=content,
                memory_type=memory_type,
                importance=importance,
                evidence=str(item.get("evidence") or "").strip()[:500],
            )
        )
    return candidates


def normalize_memory_content(content: str) -> str:
    content = str(content or "").strip().lower()
    content = re.sub(r"[^\w\s]", " ", content)
    return re.sub(r"\s+", " ", content).strip()


def _dedupe_similarity_threshold() -> float:
    raw = os.getenv("CHATBOT_MEMORY_DEDUPE_SIMILARITY", "").strip()
    if not raw:
        return _DEFAULT_DEDUPE_SIMILARITY_THRESHOLD
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_DEDUPE_SIMILARITY_THRESHOLD
    return min(1.0, max(0.0, value))


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def _nonnegative_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def _parse_embedding(raw: object) -> list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        values = raw
    else:
        text = str(raw).strip()
        if not text:
            return None
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        values = [part.strip() for part in text.split(",") if part.strip()]
    try:
        parsed = [float(value) for value in values]
    except (TypeError, ValueError):
        return None
    if not parsed or any(not math.isfinite(value) for value in parsed):
        return None
    return parsed


def _embedding_text(embedding: list[float] | tuple[float, ...] | None) -> str | None:
    if embedding is None:
        return None
    return "[" + ",".join(format(float(value), ".9g") for value in embedding) + "]"


def _cosine_similarity(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or not left:
        return None
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return None
    dot = sum(a * b for a, b in zip(left, right))
    return dot / (left_norm * right_norm)


def _embedding_duplicate(
    *,
    candidate_embedding: list[float] | None,
    candidate_type: str,
    active: list[dict],
) -> tuple[dict | None, float | None]:
    if candidate_embedding is None:
        return None, None
    threshold = _dedupe_similarity_threshold()
    best: dict | None = None
    best_similarity: float | None = None
    for old in active:
        if old["memory_type"] != candidate_type:
            continue
        old_embedding = _parse_embedding(old.get("embedding"))
        if old_embedding is None:
            continue
        similarity = _cosine_similarity(candidate_embedding, old_embedding)
        if similarity is None:
            continue
        if best_similarity is None or similarity > best_similarity:
            best = old
            best_similarity = similarity
    if best is not None and best_similarity is not None and best_similarity >= threshold:
        return best, best_similarity
    return None, best_similarity


def _looks_like_replacement(new_content: str, old_content: str) -> bool:
    new_norm = normalize_memory_content(new_content)
    old_norm = normalize_memory_content(old_content)
    if not new_norm or not old_norm:
        return False
    replacement_markers = (
        " instead of ",
        " no longer ",
        " now prefers ",
        " now wants ",
        " changed ",
        " rather than ",
    )
    return any(marker in new_norm for marker in replacement_markers) and (
        new_norm[:16] == old_norm[:16] or "user" in new_norm and "user" in old_norm
    )


def _active_memory_rows(active: list[dict]) -> list[dict]:
    return [memory for memory in active if memory.get("is_active", True)]


def _active_memory_index(active: list[dict]) -> dict[str, dict]:
    return {normalize_memory_content(m["content"]): m for m in _active_memory_rows(active)}


def _mark_memory_inactive(
    memory: dict,
    *,
    active_by_norm: dict[str, dict],
) -> None:
    memory["is_active"] = False
    active_by_norm.pop(normalize_memory_content(str(memory.get("content") or "")), None)


def _update_duplicate_memory(
    *,
    duplicate: dict,
    candidate: MemoryCandidate,
    source_message_id: int,
    embedding: list[float] | None,
    conn,
) -> int:
    memory_id = int(duplicate["id"])
    updated_importance = max(int(duplicate["importance"]), candidate.importance)
    db.update_memory(
        memory_id,
        importance=updated_importance,
        source_message_id=source_message_id,
        embedding=embedding,
        conn=conn,
    )
    duplicate["importance"] = updated_importance
    duplicate["source_message_id"] = source_message_id
    duplicate["embedding"] = _embedding_text(embedding)
    duplicate["is_active"] = True
    return memory_id


def _store_candidates(
    *,
    user_id: int,
    session_id: int,
    source_message_id: int,
    candidates: list[MemoryCandidate],
) -> dict[str, int]:
    stats = {"created": 0, "updated": 0, "deactivated": 0, "deleted": 0}

    with psycopg.connect(db.DB_URL) as conn:
        active = db.find_active_memories_for_dedupe(user_id, conn=conn)
        active_by_norm = _active_memory_index(active)
        _memory_debug(
            "store start user_id=%s session_id=%s source_message_id=%s candidates=%s active=%s",
            user_id,
            session_id,
            source_message_id,
            len(candidates),
            len(active),
        )

        for candidate in candidates:
            normalized = normalize_memory_content(candidate.content)
            existing = active_by_norm.get(normalized)
            duplicate = existing
            embedding = llm.get_embedding(candidate.content)
            similarity: float | None = None
            if duplicate is not None:
                memory_id = _update_duplicate_memory(
                    duplicate=duplicate,
                    candidate=candidate,
                    source_message_id=source_message_id,
                    embedding=embedding,
                    conn=conn,
                )
                active_by_norm = _active_memory_index(active)
                stats["updated"] += 1
                _memory_debug(
                    "updated duplicate id=%s type=%s importance=%s similarity=%s content=%r",
                    memory_id,
                    candidate.memory_type,
                    candidate.importance,
                    f"{similarity:.3f}" if similarity is not None else "exact",
                    _memory_preview(candidate.content),
                )
                continue

            for old in _active_memory_rows(active):
                if old["memory_type"] == candidate.memory_type and _looks_like_replacement(
                    candidate.content, str(old["content"])
                ):
                    old_id = int(old["id"])
                    db.deactivate_memory(old_id, conn=conn)
                    _mark_memory_inactive(old, active_by_norm=active_by_norm)
                    stats["deactivated"] += 1
                    _memory_debug(
                        "deactivated replaced id=%s type=%s old_content=%r",
                        old_id,
                        old["memory_type"],
                        _memory_preview(str(old["content"])),
                    )

            duplicate, similarity = _embedding_duplicate(
                candidate_embedding=embedding,
                candidate_type=candidate.memory_type,
                active=_active_memory_rows(active),
            )
            if duplicate is not None:
                memory_id = _update_duplicate_memory(
                    duplicate=duplicate,
                    candidate=candidate,
                    source_message_id=source_message_id,
                    embedding=embedding,
                    conn=conn,
                )
                active_by_norm = _active_memory_index(active)
                stats["updated"] += 1
                _memory_debug(
                    "updated duplicate id=%s type=%s importance=%s similarity=%s content=%r",
                    memory_id,
                    candidate.memory_type,
                    candidate.importance,
                    f"{similarity:.3f}" if similarity is not None else "exact",
                    _memory_preview(candidate.content),
                )
                continue

            memory_id = db.create_memory(
                user_id,
                session_id,
                source_message_id,
                candidate.content,
                candidate.memory_type,
                importance=candidate.importance,
                embedding=embedding,
                conn=conn,
            )
            stats["created"] += 1
            _memory_debug(
                "created id=%s type=%s importance=%s content=%r",
                memory_id,
                candidate.memory_type,
                candidate.importance,
                _memory_preview(candidate.content),
            )
            active_by_norm[normalized] = {
                "id": memory_id,
                "content": candidate.content,
                "memory_type": candidate.memory_type,
                "importance": candidate.importance,
                "embedding": _embedding_text(embedding),
                "source_message_id": source_message_id,
                "is_active": True,
            }
            active.append(active_by_norm[normalized])
        limit_stats = db.enforce_memory_limits(
            user_id,
            active_limit=_positive_int_env("CHATBOT_ACTIVE_MEMORY_LIMIT", _ACTIVE_MEMORY_LIMIT),
            total_limit=_positive_int_env("CHATBOT_TOTAL_MEMORY_LIMIT", _TOTAL_MEMORY_LIMIT),
            conn=conn,
        )
        stats["deactivated"] += limit_stats["deactivated"]
        stats["deleted"] += limit_stats["deleted"]
        if limit_stats["deactivated"] or limit_stats["deleted"]:
            _memory_debug(
                "limits applied deactivated=%s deleted=%s",
                limit_stats["deactivated"],
                limit_stats["deleted"],
            )
        conn.commit()
    return stats


def _recent_context_for_session(session_id: int) -> list[dict[str, str]]:
    rows = db.get_messages_by_session(session_id, limit=_DEFAULT_RECENT_CONTEXT_LIMIT)
    return [{"role": str(r["role"]), "content": str(r["content"])} for r in rows]


def _prompt_memory_limit(limit: int | None) -> int:
    if limit is not None:
        return max(0, int(limit))
    return _nonnegative_int_env("CHATBOT_PROMPT_MEMORY_LIMIT", _DEFAULT_PROMPT_MEMORY_LIMIT)


def _prompt_memory_line_limit() -> int:
    return _positive_int_env(
        "CHATBOT_PROMPT_MEMORY_LINE_CHAR_LIMIT",
        _DEFAULT_PROMPT_MEMORY_LINE_CHAR_LIMIT,
    )


def _truncate_memory_line(content: str, *, limit: int) -> str:
    content = re.sub(r"\s+", " ", str(content or "").strip())
    if limit <= 0 or len(content) <= limit:
        return content
    return content[: limit - 3].rstrip() + "..."


def retrieve_prompt_memories_for_user(
    user_id: int,
    *,
    query: str = "",
    limit: int | None = None,
) -> list[dict]:
    """Return prompt memories ranked by embedding relevance to the current user message."""
    prompt_limit = _prompt_memory_limit(limit)
    if prompt_limit <= 0:
        return []

    # Fallback ordering is importance DESC, updated_at DESC from db.list_active_memories().
    fallback_memories = db.list_active_memories(user_id, limit=prompt_limit)
    if not fallback_memories:
        _memory_debug("prompt retrieval fallback_empty user_id=%s", user_id)
        return []

    query_text = str(query or "").strip()
    if not query_text:
        _memory_debug(
            "prompt retrieval fallback_no_query user_id=%s selected=%s",
            user_id,
            len(fallback_memories),
        )
        return fallback_memories

    query_embedding = llm.get_embedding(query_text)
    if query_embedding is None:
        _memory_debug(
            "prompt retrieval fallback_no_embedding user_id=%s selected=%s",
            user_id,
            len(fallback_memories),
        )
        return fallback_memories

    memories = db.search_active_memories_by_embedding(
        user_id,
        query_embedding,
        limit=prompt_limit,
    )
    if not memories:
        _memory_debug(
            "prompt retrieval fallback_no_vector_matches user_id=%s selected=%s",
            user_id,
            len(fallback_memories),
        )
        return fallback_memories

    _memory_debug(
        "prompt retrieval user_id=%s query_embedding=true selected=%s",
        user_id,
        len(memories),
    )
    return memories


def build_memory_prompt_block(
    memories: list[dict],
    *,
    line_char_limit: int | None = None,
) -> str:
    """Format retrieved memories as a system-prompt background context block."""
    if not memories:
        return ""
    resolved_line_limit = (
        _prompt_memory_line_limit() if line_char_limit is None else max(0, int(line_char_limit))
    )
    lines = []
    for memory in memories:
        content = _truncate_memory_line(str(memory.get("content") or ""), limit=resolved_line_limit)
        if content:
            lines.append(f"- {content}")
    if not lines:
        return ""
    return (
        "Relevant long-term context about the user:\n"
        + "\n".join(lines)
        + "\n\nUse this context only when relevant to the current reply. "
        "Do not explicitly mention these notes unless the user directly asks."
    )


def memory_prompt_block_for_user(
    user_id: int,
    *,
    query: str = "",
    limit: int | None = None,
) -> str:
    memories = retrieve_prompt_memories_for_user(user_id, query=query, limit=limit)
    block = build_memory_prompt_block(memories)
    if not block:
        _memory_debug("prompt block skipped user_id=%s included=0", user_id)
        return ""
    _memory_debug("prompt block included user_id=%s included=%s", user_id, len(memories))
    return block


def run_memory_pipeline_for_turn(
    *,
    user_id: int,
    session_id: int,
    source_message_id: int,
    user_message: str,
    assistant_response: str,
    recent_context: list[dict[str, Any]] | None = None,
) -> None:
    """Extract durable user memories from one completed chat turn and store new candidates by calling llm.extract_memories_json().

    This runs as a best-effort background task: it gathers recent context, asks the LLM for
    structured memory candidates, parses and deduplicates them, then writes accepted memories
    to the database. Errors are logged so memory extraction does not break the chat response.
    """
    try:
        _memory_debug(
            "pipeline start user_id=%s session_id=%s source_message_id=%s user_message=%r",
            user_id,
            session_id,
            source_message_id,
            _memory_preview(user_message),
        )
        context = recent_context
        if context is None:
            context = _recent_context_for_session(session_id)
        _memory_debug("context messages=%s", len(context))
        llm_raw = llm.extract_memories_json(
            user_message=user_message,
            assistant_response=assistant_response,
            recent_context=[
                {"role": str(m.get("role") or ""), "content": str(m.get("content") or "")}
                for m in context
                if isinstance(m, dict)
            ],
        )
        candidates = parse_memory_candidates(llm_raw)
        _memory_debug("extractor raw_chars=%s candidates=%s", len(llm_raw or ""), len(candidates))
        if not candidates:
            _memory_debug("pipeline done no candidates")
            return
        stats = _store_candidates(
            user_id=user_id,
            session_id=session_id,
            source_message_id=source_message_id,
            candidates=candidates,
        )
        _memory_debug(
            "pipeline done created=%s updated=%s deactivated=%s deleted=%s",
            stats["created"],
            stats["updated"],
            stats["deactivated"],
            stats["deleted"],
        )
    except Exception:
        logger.exception("run_memory_pipeline_for_turn: memory pipeline failed")
