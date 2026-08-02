"""Shared constants and small render helpers for the Textual UI."""

from __future__ import annotations

from datetime import date
from enum import Enum

import tasks


class Mode(Enum):
    NORMAL = "NORMAL"
    COMMAND = "COMMAND"
    SEARCH = "SEARCH"
    CHAT = "CHAT"


COMMANDS = [
    "search ",
    "ask ",
    "new note ",
    "new journal",
    "new folder ",
    "open ",
    "done ",
    "today",
    "tasks",
    "reindex",
    "quit",
    "q",
]


HINTS = [
    ("j/k", "move"),
    ("h/l", "panes"),
    ("gg/G", "top/end"),
    ("gn/gj", "views"),
    ("↵", "open"),
    ("x", "done"),
    ("/", "search"),
    ("n", "new"),
    ("d", "delete"),
    ("t", "today"),
    ("c", "chat"),
    (":", "command"),
    ("^Q", "quit"),
]


SIDEBAR_ITEMS = ["Home", "Tasks", "Notes", "Journals", "Archive", "Tags"]

SIDEBAR_ICONS = {
    "Home": "⌂",
    "Tasks": "✓",
    "Notes": "≡",
    "Journals": "♦",
    "Archive": "□",
    "Tags": "#",
}


def fmt_task(t: tasks.Task) -> str:
    mark = "☑" if t.done else "☐"
    title = t.title if not t.done else f"[strike]{t.title}[/strike]"
    due = ""
    if t.due_date and t.due_date != date.today():
        due = f"  [dim]({t.due_date.strftime('%a %d %b')})[/dim]"
    src = f"  [dim]{t.source_path}[/dim]"
    return f"{mark} {title}{due}{src}"
