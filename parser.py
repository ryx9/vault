"""Parses markdown files into headings, chunks and raw TODO lines.

Markdown is the source of truth: this module only reads files, it never
writes them. Malformed content is skipped, never raised as a crash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import config

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


@dataclass
class Chunk:
    path: str          # path relative to notes/
    heading: str        # nearest heading above this text ("" if none)
    text: str


@dataclass
class TodoLine:
    line_num: int       # 0-based line index in the file
    raw_text: str       # text after the TODO: marker (without done prefix)
    done: bool


def read_file(path: Path) -> str:
    """Read a markdown file, returning '' on any error instead of raising."""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(config.NOTES_DIR))
    except ValueError:
        return str(path)


def chunk_markdown(path: Path) -> list[Chunk]:
    """Split a markdown file into chunks, one per heading section.

    Text before the first heading (if any) becomes a chunk with heading "".
    """
    text = read_file(path)
    if not text.strip():
        return []

    rel = relative_path(path)
    chunks: list[Chunk] = []
    current_heading = ""
    buffer: list[str] = []

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if body:
            chunks.append(Chunk(path=rel, heading=current_heading, text=body))

    for line in text.splitlines():
        match = HEADING_RE.match(line)
        if match:
            flush()
            buffer = []
            current_heading = match.group(2).strip()
        else:
            buffer.append(line)
    flush()

    return chunks


def _parse_todo_rest(rest: str) -> tuple[str, bool]:
    """Split a TODO body into (text, done). Leading X marks completion."""
    stripped = rest.strip()
    if not stripped:
        return "", False
    marker = config.DONE_PREFIX.upper()
    if stripped.upper().startswith(f"{marker} ") or stripped.upper().startswith(f"{marker}\t"):
        return stripped[2:].strip(), True
    return stripped, False


def extract_todo_lines(path: Path) -> list[TodoLine]:
    """Return every TODO line in a file with line number and done state."""
    text = read_file(path)
    if not text:
        return []

    todos: list[TodoLine] = []
    for line_num, line in enumerate(text.splitlines()):
        idx = line.find(config.TODO_PATTERN)
        if idx == -1:
            continue
        rest = line[idx + len(config.TODO_PATTERN):].strip()
        body, done = _parse_todo_rest(rest)
        if body:
            todos.append(TodoLine(line_num=line_num, raw_text=body, done=done))
    return todos


def extract_todo_texts(path: Path) -> list[str]:
    """Return raw TODO bodies (legacy helper for search indexing)."""
    return [t.raw_text for t in extract_todo_lines(path)]


def toggle_todo_done(path: Path, line_num: int) -> bool:
    """Flip the X done marker on a TODO line. Returns the new done state."""
    text = read_file(path)
    if not text:
        raise ValueError(f"Cannot toggle task: empty file {path}")

    lines = text.splitlines()
    if line_num < 0 or line_num >= len(lines):
        raise ValueError(f"Line {line_num} out of range in {path}")

    line = lines[line_num]
    idx = line.find(config.TODO_PATTERN)
    if idx == -1:
        raise ValueError(f"No TODO marker on line {line_num} in {path}")

    prefix = line[: idx + len(config.TODO_PATTERN)]
    rest = line[idx + len(config.TODO_PATTERN):].strip()
    body, done = _parse_todo_rest(rest)
    if not body:
        raise ValueError(f"Empty TODO on line {line_num} in {path}")

    new_done = not done
    new_body = f"{config.DONE_PREFIX} {body}" if new_done else body
    lines[line_num] = f"{prefix} {new_body}".rstrip()
    ending = "\n" if text.endswith("\n") else ""
    path.write_text("\n".join(lines) + ending, encoding="utf-8")
    return new_done


def iter_markdown_files(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(p for p in root.rglob("*.md") if p.is_file())
