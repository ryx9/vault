"""Combines keyword, fuzzy and semantic search into one ranked result list."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import config
import embeddings
import search

WEIGHT_KEYWORD = 1.2
WEIGHT_FUZZY = 0.7
WEIGHT_SEMANTIC = 1.0

BOOST_FILENAME = 0.4
BOOST_HEADING = 0.2
BOOST_TODO = 0.2
BOOST_RECENT = 0.05


@dataclass
class Result:
    path: str
    heading: str
    text: str
    score: float


def _recent_files(notes_dir: Path, limit: int = 10) -> set[str]:
    files = sorted(
        notes_dir.rglob("*.md"), key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True
    )[:limit]
    out = set()
    for f in files:
        try:
            out.add(str(f.relative_to(notes_dir)))
        except ValueError:
            continue
    return out


def _merge(scored: dict[str, Result], path: str, heading: str, text: str, score: float) -> None:
    existing = scored.get(path)
    if existing is None or score > existing.score:
        scored[path] = Result(path=path, heading=heading, text=text, score=score)
    else:
        # Same file found by multiple strategies -> reinforce its rank.
        existing.score = max(existing.score, score) + min(score, existing.score) * 0.25


def hybrid_search(query: str, top_k: int = 10, use_semantic: bool | None = None) -> list[Result]:
    if use_semantic is None:
        use_semantic = config.ENABLE_SEMANTIC_SEARCH or embeddings.chunk_count() > 0

    scored: dict[str, Result] = {}
    recent = _recent_files(config.NOTES_DIR)

    for r in search.keyword_search(query, top_k=30):
        boost = 0.0
        if r["kind"] == "filename":
            boost += BOOST_FILENAME
        elif r["kind"] == "heading":
            boost += BOOST_HEADING
        elif r["kind"] == "todo":
            boost += BOOST_TODO
        if r["path"] in recent:
            boost += BOOST_RECENT
        _merge(scored, r["path"], r["heading"], r["text"], r["score"] * WEIGHT_KEYWORD + boost)

    for r in search.fuzzy_search(query, top_k=10):
        boost = BOOST_RECENT if r["path"] in recent else 0.0
        _merge(scored, r["path"], r["heading"], r["text"], r["score"] * WEIGHT_FUZZY + boost)

    if use_semantic:
        try:
            for r in embeddings.semantic_search(query, top_k=15):
                boost = BOOST_RECENT if r["path"] in recent else 0.0
                _merge(scored, r["path"], r["heading"], r["text"], r["score"] * WEIGHT_SEMANTIC + boost)
        except Exception:
            # Semantic search is optional; fall back to keyword/fuzzy search if it fails.
            pass

    ranked = sorted(scored.values(), key=lambda r: r.score, reverse=True)
    return ranked[:top_k]
