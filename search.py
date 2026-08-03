"""Keyword search index backed by SQLite FTS5, with RapidFuzz fallback.

This index is a disposable cache derived from markdown: on any change to a
file, its rows are deleted and rebuilt. It is never the source of truth.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from rapidfuzz import fuzz, process

import config
import parser

_FTS_SPECIAL = re.compile(r'[":*^]')


def _connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(config.SEARCH_DB)
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            path, heading, content, kind, tokenize='porter'
        )
        """
    )
    return conn


def has_entries() -> bool:
    try:
        with _connect() as conn:
            return conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False


def remove_file(rel_path: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM chunks WHERE path = ?", (rel_path,))


def index_file(path: Path) -> None:
    """Rebuild all keyword-index rows for one markdown file."""
    rel = parser.relative_path(path)
    with _connect() as conn:
        conn.execute("DELETE FROM chunks WHERE path = ?", (rel,))

        rows: list[tuple[str, str, str, str]] = [(rel, "", rel, "filename")]

        for chunk in parser.chunk_markdown(path):
            if chunk.heading:
                rows.append((rel, chunk.heading, chunk.heading, "heading"))
            if chunk.text:
                rows.append((rel, chunk.heading, chunk.text, "body"))

        conn.executemany(
            "INSERT INTO chunks (path, heading, content, kind) VALUES (?, ?, ?, ?)",
            rows,
        )


def reindex_all(notes_dir: Path = config.NOTES_DIR) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM chunks")
    for md_file in parser.iter_markdown_files(notes_dir):
        index_file(md_file)


def indexed_file_count() -> int:
    with _connect() as conn:
        row = conn.execute("SELECT COUNT(DISTINCT path) FROM chunks").fetchone()
        return int(row[0]) if row else 0


def ensure_indexed(notes_dir: Path = config.NOTES_DIR) -> None:
    total = len(parser.iter_markdown_files(notes_dir))
    if total == 0:
        return
    if indexed_file_count() >= total:
        return
    reindex_all(notes_dir)


def _sanitize(query: str) -> str:
    """Turn free text into a safe FTS5 MATCH expression (prefix AND query)."""
    cleaned = re.sub(r"[^0-9A-Za-z_]+", " ", query)
    terms = [t for t in cleaned.split() if t]
    if not terms:
        return ""
    return " AND ".join(f"{t}*" for t in terms)


def _like_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def keyword_search(query: str, top_k: int = 20) -> list[dict]:
    """Exact / partial matches via FTS5, ranked by bm25."""
    match_expr = _sanitize(query)
    if not match_expr:
        return []

    with _connect() as conn:
        cur = conn.execute(
            """
            SELECT path, heading, content, kind, bm25(chunks) AS rank
            FROM chunks
            WHERE chunks MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (match_expr, top_k),
        )
        rows = cur.fetchall()

        if not rows and " AND " in match_expr:
            alt_expr = " OR ".join(f"{t}*" for t in cleaned.split())
            cur = conn.execute(
                """
                SELECT path, heading, content, kind, bm25(chunks) AS rank
                FROM chunks
                WHERE chunks MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (alt_expr, top_k),
            )
            rows = cur.fetchall()

        if not rows:
            like_term = f"%{_like_escape(query.strip())}%"
            cur = conn.execute(
                """
                SELECT path, heading, content, kind, 0.0 AS rank
                FROM chunks
                WHERE path LIKE ? ESCAPE '\\'
                   OR heading LIKE ? ESCAPE '\\'
                   OR content LIKE ? ESCAPE '\\'
                LIMIT ?
                """,
                (like_term, like_term, like_term, top_k),
            )
            rows = cur.fetchall()

    results = []
    for path, heading, content, kind, rank in rows:
        # bm25 is negative-is-better in sqlite; flip to a positive score.
        score = 1.0 / (1.0 + max(rank, 0.0)) if rank is not None else 0.5
        results.append(
            {"path": path, "heading": heading, "text": content, "kind": kind, "score": score}
        )
    return results


def fuzzy_search(query: str, top_k: int = 10) -> list[dict]:
    """Fallback fuzzy matching over filenames/headings for typo tolerance."""
    with _connect() as conn:
        cur = conn.execute("SELECT DISTINCT path, heading FROM chunks WHERE kind != 'body'")
        candidates = cur.fetchall()

    labels = [f"{path} {heading}".strip() for path, heading in candidates]
    if not labels:
        return []

    matches = process.extract(query, labels, scorer=fuzz.WRatio, limit=top_k)
    results = []
    for label, score, idx in matches:
        if score < 60:
            continue
        path, heading = candidates[idx]
        results.append(
            {"path": path, "heading": heading, "text": label, "kind": "fuzzy", "score": score / 100.0}
        )
    return results
