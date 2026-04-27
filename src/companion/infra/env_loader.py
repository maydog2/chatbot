"""Load repo-root ``.env`` once (non-destructive: does not override existing env vars)."""

from __future__ import annotations

import sys
from pathlib import Path

_LOADED = False


def _repo_root() -> Path:
    """Find the project root by walking upward from this file."""
    for path in Path(__file__).resolve().parents:
        if (path / "pyproject.toml").exists() or (path / "requirements.txt").exists() or (path / ".git").exists():
            return path
    return Path(__file__).resolve().parents[3]


def load_repo_dotenv() -> None:
    """
    Load ``<project_root>/.env`` if ``python-dotenv`` is installed.

    Skipped when pytest is active so tests keep using ``TEST_DB_URL`` / conftest overrides
    instead of a developer's local ``.env`` (e.g. Neon production).
    """
    global _LOADED
    if _LOADED:
        return
    if sys.modules.get("pytest") is not None:
        _LOADED = True
        return
    try:
        from dotenv import load_dotenv
    except ImportError:
        _LOADED = True
        return
    load_dotenv(_repo_root() / ".env", override=False)
    _LOADED = True
