"""
companion/infra — Persistence, external APIs, and DB tooling.

Subpackages / modules (import examples):
  db — ``from companion.infra import db`` (Postgres CRUD + pool; see infra/db/__init__.py)
  llm — ``from companion.infra import llm`` or ``companion.infra.llm.get_reply``
  init_db — CLI: ``python -m companion.infra.init_db``
  list_tables — CLI: ``python -m companion.infra.list_tables``

This file is intentionally minimal; concrete callables live in the submodules above.
"""
