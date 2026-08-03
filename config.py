"""Central configuration: paths and constants. Nothing here touches note content."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load secrets and overrides from .env in the project root (uv-managed venv).
load_dotenv(BASE_DIR / ".env")

NOTES_DIR = BASE_DIR / "notes"
JOURNAL_DIR = NOTES_DIR / "journal"

PKB_DIR = BASE_DIR / ".pkb"
CHROMA_DIR = PKB_DIR / "chroma"
CACHE_DIR = PKB_DIR / "cache"
LOGS_DIR = PKB_DIR / "logs"
SEARCH_DB = PKB_DIR / "search.db"
META_DB = PKB_DIR / "meta.db"

EMBEDDING_MODEL = os.environ.get(
    "PKB_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
CHROMA_COLLECTION = "pkb_chunks"
ENABLE_SEMANTIC_SEARCH = os.environ.get("PKB_ENABLE_SEMANTIC_SEARCH", "0").lower() in (
    "1",
    "true",
    "yes",
)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.environ.get("PKB_LLM_MODEL", "google/gemma-3-12b-it:free")

TODO_PATTERN = "TODO:"
DONE_PREFIX = "X"


def ensure_dirs() -> None:
    """Create every directory the app needs. Safe to call repeatedly."""
    for d in (NOTES_DIR, JOURNAL_DIR, PKB_DIR, CHROMA_DIR, CACHE_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
