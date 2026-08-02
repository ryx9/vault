"""SQLite metadata store synced with markdown task lines.

Markdown remains the source of truth; this DB mirrors task state for fast
queries and survives line-number lookups across UI refreshes.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import config
import parser
import tasks

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    line_num INTEGER NOT NULL,
    title TEXT NOT NULL,
    due_date TEXT,
    done INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT NOT NULL,
    UNIQUE(path, line_num)
);
CREATE INDEX IF NOT EXISTS idx_tasks_path ON tasks(path);
CREATE INDEX IF NOT EXISTS idx_tasks_done ON tasks(done);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.META_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def sync_tasks(notes_dir: Path = config.NOTES_DIR) -> None:
    """Reconcile the tasks table with every TODO line on disk."""
    seen: set[tuple[str, int]] = set()
    rows: list[tuple[str, int, str, str | None, int, str]] = []

    for md_file in parser.iter_markdown_files(notes_dir):
        rel = parser.relative_path(md_file)
        for todo in parser.extract_todo_lines(md_file):
            title, due = tasks.parse_task_text(todo.raw_text)
            due_str = due.isoformat() if due else None
            rows.append((rel, todo.line_num, title, due_str, int(todo.done), todo.raw_text))
            seen.add((rel, todo.line_num))

    with _connect() as conn:
        conn.execute("DELETE FROM tasks")
        conn.executemany(
            """
            INSERT INTO tasks (path, line_num, title, due_date, done, raw_text)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def load_tasks(include_done: bool = False) -> list[tasks.Task]:
    """Return tasks from the synced DB."""
    clause = "" if include_done else "WHERE done = 0"
    with _connect() as conn:
        cur = conn.execute(
            f"""
            SELECT path, line_num, title, due_date, done, raw_text
            FROM tasks
            {clause}
            ORDER BY due_date IS NULL, due_date, path, line_num
            """
        )
        result: list[tasks.Task] = []
        for row in cur.fetchall():
            due: date | None = None
            if row["due_date"]:
                due = date.fromisoformat(row["due_date"])
            result.append(
                tasks.Task(
                    title=row["title"],
                    due_date=due,
                    source_path=row["path"],
                    raw_text=row["raw_text"],
                    line_num=row["line_num"],
                    done=bool(row["done"]),
                )
            )
        return result


def toggle_task(path: str, line_num: int) -> bool:
    """Flip done state in markdown and resync. Returns the new done value."""
    full = config.NOTES_DIR / path
    new_done = parser.toggle_todo_done(full, line_num)
    sync_tasks()
    return new_done


def task_counts() -> dict[str, int]:
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        open_count = conn.execute("SELECT COUNT(*) FROM tasks WHERE done = 0").fetchone()[0]
        done = conn.execute("SELECT COUNT(*) FROM tasks WHERE done = 1").fetchone()[0]
    return {"total": total, "open": open_count, "done": done}
