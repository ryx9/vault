"""Command-bar parsing and command implementations."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from textual import work
from textual.widgets import Input, RichLog

import db
import embeddings
import notes as notes_fs
import parser
import retriever
import search
import tasks
from ui_constants import COMMANDS, Mode, fmt_task


class CommandMixin:
    mode: Mode
    _cmd_prefix: str
    _cmd_submit_prefix: str

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "cmd":
            return
        self._cmd_prefix = event.value
        val = event.value.lstrip(":;")
        if not val and self.focused is event.input:
            self.mode = Mode.COMMAND
        elif not val:
            self.mode = Mode.NORMAL
        elif val.startswith("search ") or val == "search":
            self.mode = Mode.SEARCH
        else:
            self.mode = Mode.COMMAND
        self._update_mode_badge()

    def _handle_cmd_submit(self, event: Input.Submitted) -> None:
        raw = f"{self._cmd_submit_prefix}{event.value.strip()}".strip()
        event.input.value = ""
        event.input.placeholder = "Type a command"
        self._cmd_prefix = ""
        self._cmd_submit_prefix = ""
        self.mode = Mode.NORMAL
        self._update_mode_badge()
        self.set_focus(self.query_one("#dashboard_list"))

        if not raw:
            return

        raw = raw.lstrip(":;").strip()
        if not raw:
            return

        if self._handle_natural_language(raw):
            return

        parts = raw.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        handlers = {
            "quit": lambda: self.exit(),
            "q": lambda: self.exit(),
            "today": lambda: self.open_in_editor(notes_fs.ensure_today_journal()),
            "reindex": self._cmd_reindex,
            "tasks": self._cmd_tasks,
            "search": lambda: self._cmd_search(arg),
            "s": lambda: self._cmd_search(arg),
            "ask": lambda: self._cmd_ask_via_chat(arg),
            "new": lambda: self._cmd_new(arg),
            "open": lambda: self._cmd_open(arg),
            "done": lambda: self._cmd_done(arg),
        }

        handler = handlers.get(cmd)
        if handler:
            handler()
        else:
            self._chat_write_system(
                f"unknown command: [bold]{cmd}[/bold] - try: search, ask, new note, today, quit"
            )

    def _handle_natural_language(self, raw: str) -> bool:
        lowered = raw.lower()
        if lowered.startswith("create task "):
            self._chat_write_system("use TODO: in a note to create a task - open a note first")
            return True
        if lowered.startswith("open journal"):
            arg = lowered.replace("open journal", "", 1).strip()
            if not arg or arg in {"today", "yesterday", "tomorrow"}:
                if arg == "yesterday":
                    target = date.today() - timedelta(days=1)
                elif arg == "tomorrow":
                    target = date.today() + timedelta(days=1)
                else:
                    target = date.today()
                self.open_in_editor(notes_fs.ensure_journal(target))
                return True
            self._chat_write_system(f"unrecognized journal date: {arg}")
            return True
        if lowered.startswith("search "):
            query = raw[len("search "):].strip()
            if query:
                self._cmd_search(query)
            return True
        if lowered.startswith("new note"):
            arg = raw[len("new note"):].strip()
            if arg:
                self._create_note(arg)
                return True
            self._chat_write_system("usage: new note <name>")
            return True
        return False

    def _cmd_reindex(self) -> None:
        self._chat_write_system("reindexing...")
        n_chunks = embeddings.reindex_all()
        search.reindex_all()
        db.sync_tasks()
        self.refresh_dashboard()
        self._chat_write_system(f"reindex complete - {n_chunks} chunks embedded")

    def _cmd_tasks(self) -> None:
        groups = tasks.group_tasks(db.load_tasks(include_done=True))
        lines = ["[bold]due today[/bold]"] + ([fmt_task(t) for t in groups["due_today"]] or ["  none"])
        lines += ["\n[bold]upcoming[/bold]"] + ([fmt_task(t) for t in groups["upcoming"]] or ["  none"])
        lines += ["\n[bold]no due date[/bold]"] + ([fmt_task(t) for t in groups["no_date"]] or ["  none"])
        lines += ["\n[bold]done[/bold]"] + ([fmt_task(t) for t in groups["done"][:10]] or ["  none"])
        log = self.query_one("#chat_log", RichLog)
        for line in "\n".join(lines).splitlines():
            log.write(f"  {line}")

    def _cmd_search(self, query: str) -> None:
        if not query:
            self._chat_write_system("usage: search <query>")
            return
        self.mode = Mode.SEARCH
        self._update_mode_badge()
        self._chat_write_system(f"[dim]searching for '{query}'...[/dim]")
        self._start_search(query)

    @work(thread=True)
    def _start_search(self, query: str) -> None:
        results = retriever.hybrid_search(query, top_k=10)
        self.call_from_thread(self._finish_search, query, results)

    def _finish_search(self, query: str, results: list[retriever.Result]) -> None:
        self._populate_search_results(results)
        if not results:
            self._chat_write_system(f"no results for '{query}'")
            self.set_focus(self.query_one("#dashboard_list"))
        else:
            self._chat_write_system(
                f"[dim]{len(results)} results for '{query}' - enter to open · Esc to clear[/dim]"
            )
            search_list = self.query_one("#search_list")
            self.set_focus(search_list)
            if hasattr(search_list, "index"):
                search_list.index = 0
        self.mode = Mode.NORMAL
        self._update_mode_badge()

    def _cmd_ask_via_chat(self, question: str) -> None:
        if not question:
            self._chat_write_system("usage: ask <question>")
            return
        chat_input = self.query_one("#chat_input", Input)
        chat_input.value = question
        self.set_focus(chat_input)
        self._handle_chat_submit(
            type("_E", (), {"value": question, "input": chat_input})()
        )

    def _cmd_new(self, arg: str) -> None:
        if not arg:
            self._chat_write_system("usage: new note <name> | new journal [date] | new folder <name>")
            return
        sub_parts = arg.split(maxsplit=1)
        kind = sub_parts[0].lower()
        name = sub_parts[1].strip() if len(sub_parts) > 1 else ""
        if kind == "note":
            self._create_note(name)
        elif kind == "journal":
            self._create_journal(name)
        elif kind == "folder":
            self._create_folder(name)
        else:
            self._chat_write_system("usage: new note <name> | new journal [YYYY-MM-DD] | new folder <name>")

    def _create_note(self, spec: str) -> None:
        if not spec:
            self._chat_write_system("usage: new note <name> or new note folder/name")
            return
        folder, name = spec.rsplit("/", 1) if "/" in spec else ("", spec)
        try:
            path = notes_fs.create_note(name, folder)
            rel = parser.relative_path(path)
            self._chat_write_system(f"created {rel}")
            self.open_in_editor(path)
        except FileExistsError:
            existing = notes_fs.resolve_note_path(
                f"{folder}/{name}" if folder else name
            )
            if existing:
                rel = parser.relative_path(existing)
                self._chat_write_system(f"opened existing note: {rel}")
                self.open_in_editor(existing)
            else:
                self._chat_write_system(
                    f"note already exists but could not resolve path: {name}"
                )

    def _create_journal(self, date_str: str) -> None:
        if date_str:
            try:
                day = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                self._chat_write_system("usage: new journal YYYY-MM-DD")
                return
        else:
            day = date.today()
        path = notes_fs.ensure_journal(day)
        self._chat_write_system(f"journal ready: {parser.relative_path(path)}")
        self.open_in_editor(path)

    def _create_folder(self, name: str) -> None:
        if not name:
            self._chat_write_system("usage: new folder <name>")
            return
        try:
            path = notes_fs.create_folder(name)
            self._chat_write_system(f"created folder: {parser.relative_path(path)}")
            self.refresh_dashboard()
        except FileExistsError:
            self._chat_write_system(f"folder already exists: {name}")

    def _cmd_open(self, spec: str) -> None:
        if not spec:
            self._chat_write_system("usage: open <path/to/note.md>")
            return
        path = notes_fs.resolve_note_path(spec)
        if path:
            self.open_in_editor(path)
        else:
            self._chat_write_system(f"note not found: {spec}")

    def _cmd_done(self, spec: str) -> None:
        if not spec or ":" not in spec:
            self._chat_write_system("usage: done <path>:<line_num> or select a task and press x")
            return
        self._toggle_task_by_key(spec)
