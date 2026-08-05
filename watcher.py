"""Watches notes/ and incrementally updates indexes on change.

No manual refresh, no full reindex on every keystroke: only the file that
changed gets its embeddings and keyword rows regenerated.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
import db
import embeddings
import search
import tasks


class _MarkdownHandler(FileSystemEventHandler):
    def __init__(self, on_change: Callable[[Path], None]):
        self.on_change = on_change
        self._last_seen: dict[str, float] = {}

    def _debounced(self, path_str: str) -> bool:
        now = time.time()
        last = self._last_seen.get(path_str, 0)
        self._last_seen[path_str] = now
        return now - last > 0.3  # collapse rapid duplicate save events

    def _handle(self, path_str: str, deleted: bool = False) -> None:
        if not path_str.endswith(".md"):
            return
        if not self._debounced(path_str):
            return
        path = Path(path_str)
        rel = str(path.relative_to(config.NOTES_DIR)) if path.is_absolute() else path_str
        try:
            rel = str(path.resolve().relative_to(config.NOTES_DIR.resolve()))
        except ValueError:
            pass

        if deleted:
            embeddings.remove_file_embeddings(rel)
            search.remove_file(rel)
        else:
            tasks.canonicalize_task_dates_in_file(path)
            embeddings.reindex_file(path)
            search.index_file(path)

        db.sync_tasks()
        self.on_change(path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            self._handle(event.src_path, deleted=True)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.src_path, deleted=True)
            self._handle(event.dest_path)


def start_watching(on_change: Callable[[Path], None]) -> Observer:
    config.ensure_dirs()
    handler = _MarkdownHandler(on_change)
    observer = Observer()
    observer.schedule(handler, str(config.NOTES_DIR), recursive=True)
    observer.start()
    return observer
