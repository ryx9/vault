"""Combines keyword, fuzzy and semantic search into one ranked result list."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import config
import embeddings
import parser
import search

WEIGHT_KEYWORD = 1.2
WEIGHT_FUZZY = 0.65
WEIGHT_SEMANTIC = 1.1

BOOST_FILENAME = 0.45
BOOST_HEADING = 0.25
BOOST_TODO = 0.2
BOOST_RECENT = 0.12
BOOST_PATH = 0.35
BOOST_PATH_ALL = 0.22
BOOST_PATH_PART = 0.13


@dataclass
class Result:
    path: str
    heading: str
    text: str
    score: float


def _recent_scores(notes_dir: Path) -> dict[str, float]:
    files = sorted(
        parser.iter_markdown_files(notes_dir),
        key=lambda p: p.stat().st_mtime if p.exists() else 0,
        reverse=True,
    )
    if not files:
        return {}
    total = len(files)
    scores: dict[str, float] = {}
    for index, f in enumerate(files):
        try:
            rel = str(f.relative_to(notes_dir))
        except ValueError:
            continue
        scores[rel] = max(0.0, (total - index) / total)
    return scores


def _path_boost(path: str, heading: str, query: str) -> float:
    query_terms = [t for t in re.split(r"[^0-9a-z]+", query.lower()) if t]
    if not query_terms:
        return 0.0

    lower_path = path.lower()
    lower_heading = heading.lower()
    if all(term in lower_path for term in query_terms):
        return BOOST_PATH
    if all(term in lower_heading for term in query_terms):
        return BOOST_PATH * 0.75
    if any(term in lower_path for term in query_terms):
        return BOOST_PATH_PART
    if any(term in lower_heading for term in query_terms):
        return BOOST_PATH_PART * 0.75
    return 0.0


def _graph_neighbor_paths(results: list[Result]) -> set[str]:
    neighbors: set[str] = set()
    for result in results[:6]:
        for reference in parser.extract_references_from_text(result.text, base_path=result.path):
            neighbors.add(reference)
    return neighbors


def _add_graph_neighbors(scored: dict[str, Result], query: str, recent_scores: dict[str, float]) -> None:
    graph_paths = _graph_neighbor_paths(sorted(scored.values(), key=lambda r: r.score, reverse=True))
    if not graph_paths:
        return

    for path in list(graph_paths)[:8]:
        file_path = config.NOTES_DIR / path
        if not file_path.exists() or not file_path.is_file():
            continue
        for chunk in parser.chunk_markdown(file_path):
            boost = BOOST_GRAPH + _path_boost(path, chunk.heading, query)
            boost += BOOST_RECENT * recent_scores.get(path, 0.0)
            _merge(scored, chunk.path, chunk.heading, chunk.text, boost)


def _merge(scored: dict[str, Result], path: str, heading: str, text: str, score: float) -> None:
    existing = scored.get(path)
    if existing is None or score > existing.score:
        scored[path] = Result(path=path, heading=heading, text=text, score=score)
    else:
        existing.score = max(existing.score, score) + min(score, existing.score) * 0.25


def hybrid_search(query: str, top_k: int = 10, use_semantic: bool | None = None) -> list[Result]:
    if use_semantic is None:
        use_semantic = config.ENABLE_SEMANTIC_SEARCH or embeddings.chunk_count() > 0

    scored: dict[str, Result] = {}
    recent_scores = _recent_scores(config.NOTES_DIR)
    query_lower = query.lower()

    keyword_results = search.keyword_search(query, top_k=30)
    if not keyword_results:
        keyword_results = search.keyword_search(query, top_k=30)
    for r in keyword_results:
        boost = 0.0
        if r["kind"] == "filename":
            boost += BOOST_FILENAME
        elif r["kind"] == "heading":
            boost += BOOST_HEADING
        elif r["kind"] == "todo":
            boost += BOOST_TODO
        path_boost = _path_boost(r["path"], r["heading"], query)
        boost += path_boost
        boost += BOOST_RECENT * recent_scores.get(r["path"], 0.0)
        score = r["score"] * WEIGHT_KEYWORD + boost
        _merge(scored, r["path"], r["heading"], r["text"], score)

    for r in search.fuzzy_search(query, top_k=10):
        boost = _path_boost(r["path"], r["heading"], query)
        boost += BOOST_RECENT * recent_scores.get(r["path"], 0.0)
        score = r["score"] * WEIGHT_FUZZY + boost
        _merge(scored, r["path"], r["heading"], r["text"], score)

    if use_semantic:
        try:
            for r in embeddings.semantic_search(query, top_k=15):
                path_boost = _path_boost(r["path"], r["heading"], query)
                boost = path_boost + BOOST_RECENT * recent_scores.get(r["path"], 0.0)
                _merge(scored, r["path"], r["heading"], r["text"], max(r["score"], 0.0) * WEIGHT_SEMANTIC + boost)
        except Exception:
            pass

    _add_graph_neighbors(scored, query, recent_scores)

    if not scored and query_lower:
        # Guarantee that a plain path or filename match is still surfaced.
        for r in search.fuzzy_search(query, top_k=30):
            _merge(scored, r["path"], r["heading"], r["text"], r["score"] * WEIGHT_FUZZY)

    ranked = sorted(scored.values(), key=lambda r: r.score, reverse=True)
    return ranked[:top_k]
