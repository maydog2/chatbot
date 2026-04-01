"""
companion/domain — Pure business rules (no HTTP, no direct DB).

Modules:
  interests — bot primary/secondary interest taxonomy, validation, prompt snippets
  initiative — base vs effective conversational initiative (score, band, LLM instruction text)
  relationship_triggers — per-turn trigger IDs → relationship/mood deltas; mood axis math
  personality — user-chosen game reply style (tsundere / playful / cool / gentle), stored on ``bots.personality``

Typical imports:
  ``from companion.domain import interests``
  ``from companion.domain import initiative``
  ``from companion.domain import relationship_triggers``
  ``from companion.domain.personality import normalize_game_reply_style``
"""
