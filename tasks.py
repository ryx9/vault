"""Extracts tasks from markdown TODO: markers.

Done tasks are marked with a leading X after TODO: (e.g. `TODO: X buy milk`).
The UI can toggle completion, writing the marker back to markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import dateparser.search

import config
import parser

NO_DUE_DATE = "No Due Date"

_LEADING_MODIFIERS = ("next", "this", "last", "coming", "upcoming")


@dataclass
class Task:
    title: str
    due_date: date | None
    source_path: str
    raw_text: str
    line_num: int
    done: bool = False


def _expand_phrase(text: str, phrase: str) -> str:
    idx = text.find(phrase)
    if idx == -1:
        return phrase
    before = text[:idx]
    before_stripped = before.rstrip()
    for modifier in _LEADING_MODIFIERS:
        if before_stripped.lower().endswith(modifier):
            start = len(before_stripped) - len(modifier)
            return text[start:idx] + phrase
    return phrase


def _strip_date_phrase(text: str, phrase: str) -> str:
    expanded = _expand_phrase(text, phrase)
    cleaned = text.replace(expanded, "")
    cleaned = cleaned.strip(" \t-,.")
    return cleaned or text.strip()


def parse_task_text(raw_text: str) -> tuple[str, date | None]:
    """Return (title, due_date) for a single TODO line's text."""
    matches = dateparser.search.search_dates(
        raw_text,
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": datetime.now()},
    )
    if not matches:
        return raw_text.strip(), None

    phrase, parsed_dt = matches[0]
    if len(phrase.strip()) < 2:
        return raw_text.strip(), None

    title = _strip_date_phrase(raw_text, phrase)
    return title, parsed_dt.date()


def canonicalize_task_text(raw_text: str) -> str:
    """Return a task body with the first date phrase rewritten as ISO date."""
    matches = dateparser.search.search_dates(
        raw_text,
        settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": datetime.now()},
    )
    if not matches:
        return raw_text

    phrase, parsed_dt = matches[0]
    if len(phrase.strip()) < 2:
        return raw_text

    expanded = _expand_phrase(raw_text, phrase)
    iso_date = parsed_dt.date().isoformat()
    if expanded == iso_date:
        return raw_text
    return raw_text.replace(expanded, iso_date, 1)


def canonicalize_task_dates_in_file(path: Path) -> bool:
    """Rewrite TODO lines in a file to use explicit ISO due dates."""
    text = parser.read_file(path)
    if not text:
        return False

    lines: list[str] = []
    changed = False
    for line in text.splitlines():
        idx = line.find(config.TODO_PATTERN)
        if idx == -1:
            lines.append(line)
            continue

        rest = line[idx + len(config.TODO_PATTERN) :].strip()
        body, done = parser._parse_todo_rest(rest)
        if not body:
            lines.append(line)
            continue

        canonical_body = canonicalize_task_text(body)
        if done:
            canonical_body = f"{config.DONE_PREFIX} {canonical_body}"

        if canonical_body != rest:
            prefix = line[: idx + len(config.TODO_PATTERN)]
            lines.append(f"{prefix} {canonical_body}".rstrip())
            changed = True
        else:
            lines.append(line)

    if not changed:
        return False

    ending = "\n" if text.endswith("\n") else ""
    path.write_text("\n".join(lines) + ending, encoding="utf-8")
    return True


def extract_tasks_from_file(path: Path) -> list[Task]:
    rel = parser.relative_path(path)
    result: list[Task] = []
    for todo in parser.extract_todo_lines(path):
        title, due = parse_task_text(todo.raw_text)
        result.append(
            Task(
                title=title,
                due_date=due,
                source_path=rel,
                raw_text=todo.raw_text,
                line_num=todo.line_num,
                done=todo.done,
            )
        )
    return result


def extract_all_tasks(
    notes_dir: Path = config.NOTES_DIR,
    include_done: bool = False,
) -> list[Task]:
    result: list[Task] = []
    for md_file in parser.iter_markdown_files(notes_dir):
        for task in extract_tasks_from_file(md_file):
            if include_done or not task.done:
                result.append(task)
    return result


def group_tasks(task_list: list[Task]) -> dict[str, list[Task]]:
    """Group open tasks into due_today / upcoming / no_date for the dashboard."""
    today = date.today()
    groups: dict[str, list[Task]] = {"due_today": [], "upcoming": [], "no_date": [], "done": []}
    for t in task_list:
        if t.done:
            groups["done"].append(t)
            continue
        if t.due_date is None:
            groups["no_date"].append(t)
        elif t.due_date == today:
            groups["due_today"].append(t)
        elif t.due_date > today:
            groups["upcoming"].append(t)
        else:
            groups["due_today"].append(t)
    groups["upcoming"].sort(key=lambda t: t.due_date or today)
    return groups
