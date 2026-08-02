"""The dashboard: browse notes, manage journals, search, chat, and track tasks."""

from __future__ import annotations

import subprocess
from pathlib import Path

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Input, Label, ListItem, ListView, RichLog, Static, Tree

import config
import db
import llm
import notes as notes_fs
import parser
import retriever
import search
import tasks
import watcher
from ui_commands import CommandMixin
from ui_constants import COMMANDS, HINTS, SIDEBAR_ICONS, SIDEBAR_ITEMS, Mode
from ui_styles import CSS
from ui_views import DashboardViewsMixin


class PKBApp(CommandMixin, DashboardViewsMixin, App):
    ENABLE_COMMAND_PALETTE = False
    CSS = CSS

    BINDINGS = [
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+1", "focus_sidebar", "Sidebar"),
        ("ctrl+2", "focus_main", "Main"),
        ("ctrl+3", "focus_chat", "Chat"),
    ]

    def __init__(self, *, ansi_color: bool | None = None):
        super().__init__(ansi_color=ansi_color)
        self._observer = None
        self._task_items: list[tasks.Task] = []
        self._search_items: list[retriever.Result] = []
        self.current_tab = "Home"
        self.mode = Mode.NORMAL
        self._cmd_prefix = ""
        self._cmd_submit_prefix = ""
        self._chat_history: list[dict] = []
        self._chat_busy = False
        self._pending_delete: str | None = None
        self._key_prefix: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with Horizontal(id="main"):
            with Vertical(id="sidebar", classes="panel"):
                yield Label("WORKSPACE", classes="panel-title")
                yield ListView(id="sidebar_list")
            with Vertical(id="notes_pane", classes="panel"):
                yield Label("Home", classes="panel-title", id="dashboard_title")
                yield Static("", id="search_results_bar")
                yield ListView(id="dashboard_list")
                yield ListView(id="search_list")
            with Vertical(id="chat_pane", classes="panel"):
                yield Label("CHAT", classes="panel-title")
                yield RichLog(id="chat_log", highlight=False, markup=True, wrap=True)
                yield Static("", id="chat_thinking")
                with Horizontal(id="chat_input_row"):
                    yield Label(">", id="chat_prompt_label")
                    yield Input(placeholder="Ask about your notes", id="chat_input")
        with Vertical(id="bottom_bar"):
            with Horizontal(id="command_row"):
                yield Static("NORMAL", id="mode_badge")
                yield Static(":", id="cmd_prompt")
                yield Input(placeholder="Type a command", id="cmd")
            with Horizontal(id="footer_meta"):
                yield Static("Ready", id="status_line")
                yield Static(self._render_hints(), id="hints")

    def on_mount(self) -> None:
        config.ensure_dirs()
        notes_fs.ensure_today_journal()
        search.ensure_indexed()
        self.refresh_dashboard()
        llm_status = "LLM ready" if config.OPENROUTER_API_KEY else "no LLM key"
        self._chat_write_system(
            f"Ready - {llm_status}. Ask anything about your notes, or use the command bar below."
        )
        self._observer = watcher.start_watching(self._on_file_change)
        self.set_focus(self.query_one("#dashboard_list", ListView))

    def on_unmount(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1)

    def _on_file_change(self, _path: Path) -> None:
        self.call_from_thread(self.refresh_dashboard)

    def _render_hints(self) -> str:
        parts = [f"[dim]{key}[/dim] {label}" for key, label in HINTS]
        return "  ".join(parts)

    def _update_mode_badge(self) -> None:
        badge = self.query_one("#mode_badge", Static)
        badge.remove_class("mode-command", "mode-search", "mode-chat")
        badge.update(self.mode.value)
        if self.mode == Mode.COMMAND:
            badge.add_class("mode-command")
        elif self.mode == Mode.SEARCH:
            badge.add_class("mode-search")
        elif self.mode == Mode.CHAT:
            badge.add_class("mode-chat")

    def _announce_navigation(self) -> None:
        icon = SIDEBAR_ICONS.get(self.current_tab, "")
        self._set_status(f"view: {icon} {self.current_tab}".strip())

    def _set_status(self, text: str) -> None:
        self.query_one("#status_line", Static).update(text)

    def _chat_write_system(self, text: str) -> None:
        self._set_status(text)
        log = self.query_one("#chat_log", RichLog)
        log.write(f"[dim]status[/dim]  {text}")

    def _chat_write_user(self, text: str) -> None:
        log = self.query_one("#chat_log", RichLog)
        log.write("")
        log.write(f"[bold]you[/bold]")
        log.write(f"  {text}")

    def _chat_write_assistant(self, text: str, sources: list[str] | None = None) -> None:
        log = self.query_one("#chat_log", RichLog)
        log.write("")
        log.write("[bold]pkb[/bold]")
        for line in text.strip().splitlines():
            log.write(f"  {line}")
        if sources:
            log.write(f"[dim]  sources: {', '.join(sources)}[/dim]")
        log.write("")

    def _chat_set_thinking(self, active: bool) -> None:
        widget = self.query_one("#chat_thinking", Static)
        if active:
            widget.add_class("visible")
            widget.update("[dim]  thinking...[/dim]")
        else:
            widget.remove_class("visible")
            widget.update("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat_input":
            self._handle_chat_submit(event)
        elif event.input.id == "cmd":
            self._handle_cmd_submit(event)

    def _handle_chat_submit(self, event: Input.Submitted) -> None:
        question = event.value.strip()
        event.input.value = ""
        if not question or self._chat_busy:
            return
        self._chat_write_user(question)
        self._chat_history.append({"role": "user", "content": question})
        self._chat_busy = True
        self._chat_set_thinking(True)
        self.mode = Mode.CHAT
        self._update_mode_badge()
        self._run_llm_query(question)

    @work(thread=True)
    def _run_llm_query(self, question: str) -> None:
        try:
            result = llm.ask(question, history=self._chat_history[:-1])
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(self._chat_finish_error, str(exc))
            return
        self.call_from_thread(self._chat_finish, result)

    def _chat_finish(self, result: dict) -> None:
        self._chat_busy = False
        self._chat_set_thinking(False)
        self.mode = Mode.NORMAL
        self._update_mode_badge()

        answer = result.get("answer", "")
        chunks = result.get("chunks", [])

        if not answer and not chunks:
            self._chat_write_assistant("No relevant notes found.")
            return

        if not answer:
            self._chat_write_assistant(
                "(no LLM key configured - showing retrieved notes)",
                sources=[c.path for c in chunks],
            )
        else:
            sources = [c.path for c in chunks] if chunks else None
            self._chat_write_assistant(answer, sources=sources)
            self._chat_history.append({"role": "assistant", "content": answer})

        if chunks:
            self._populate_search_results(chunks)

    def _chat_finish_error(self, msg: str) -> None:
        self._chat_busy = False
        self._chat_set_thinking(False)
        self.mode = Mode.NORMAL
        self._update_mode_badge()
        self._chat_write_system(f"error: {msg}")

    def action_focus_chat(self) -> None:
        self._focus_widget("#chat_input", "chat")

    def open_in_editor(self, path: Path) -> None:
        try:
            with self.suspend():
                subprocess.run(["nvim", str(path)], check=False)
        except FileNotFoundError:
            self._chat_write_system("editor not found: nvim is not installed or not in PATH")
            return
        self.refresh_dashboard()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data or data.get("kind") != "note":
            return
        path = notes_fs.resolve_note_path(data["path"])
        if path:
            self.open_in_editor(path)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if not event.item:
            return
        self._activate_list_item(event.list_view, event.item)

    def _activate_list_item(self, list_view: ListView, item: ListItem) -> None:
        if not item.name:
            return
        name = item.name

        if list_view.id == "sidebar_list":
            if name in SIDEBAR_ITEMS:
                self.current_tab = name
                self._clear_search_results()
                self.refresh_dashboard()
                self._announce_navigation()
            return

        if list_view.id == "dashboard_list":
            if self.current_tab == "Tasks" and ":" in name:
                self._toggle_task_by_key(name)
                return
            if ":" in name:
                src_candidate = name.rsplit(":", 1)[0]
                if src_candidate.endswith(".md"):
                    self._toggle_task_by_key(name)
                    return
            path = notes_fs.resolve_note_path(name)
            if path:
                self.open_in_editor(path)
            return

        if list_view.id == "search_list":
            path = notes_fs.resolve_note_path(name)
            if path:
                self.open_in_editor(path)
            return

    def _toggle_task_by_key(self, key: str) -> None:
        self._pending_delete = None
        path_str, line_str = key.rsplit(":", 1)
        try:
            new_done = db.toggle_task(path_str, int(line_str))
            state = "done" if new_done else "open"
            self._chat_write_system(f"task marked {state}: {path_str}")
        except (ValueError, OSError) as exc:
            self._chat_write_system(f"could not toggle task: {exc}")
        self.refresh_dashboard()

    def action_toggle_task(self) -> None:
        dash = self.query_one("#dashboard_list", ListView)
        if dash.index is None:
            return
        item = dash.children[dash.index]
        if item.name and ":" in item.name:
            self._toggle_task_by_key(item.name)

    def _selected_note_path(self) -> Path | None:
        focused = self.focused
        if isinstance(focused, ListView) and focused.id == "search_list":
            item = focused.highlighted_child
        else:
            dash = self.query_one("#dashboard_list", ListView)
            item = dash.highlighted_child

        if not item or not item.name:
            return None
        if ":" in item.name:
            return None
        return notes_fs.resolve_note_path(item.name)

    def action_delete_note(self) -> None:
        path = self._selected_note_path()
        if not path:
            self._pending_delete = None
            self._chat_write_system("select a note or journal first, then press d")
            return

        rel = parser.relative_path(path)
        if self._pending_delete != rel:
            self._pending_delete = rel
            self._chat_write_system(f"delete {rel}? press d again to confirm")
            return

        try:
            deleted = notes_fs.delete_note(path)
        except OSError as exc:
            self._chat_write_system(f"could not delete note: {exc}")
            return

        self._pending_delete = None
        db.sync_tasks()
        self._clear_search_results()
        self.refresh_dashboard()
        self._chat_write_system(f"deleted {deleted} and removed cached indexes")

    def action_focus_sidebar(self) -> None:
        self._focus_widget("#sidebar_list", "sidebar")

    def _focus_widget(self, selector: str, label: str) -> None:
        self._pending_delete = None
        self.set_focus(self.query_one(selector))
        if selector == "#chat_input":
            self.mode = Mode.CHAT
        else:
            self.mode = Mode.NORMAL
        self._update_mode_badge()
        self._set_status(f"focus: {label}")

    def _focus_search_or_main(self) -> None:
        if self._search_items:
            self._focus_widget("#search_list", "search results")
        else:
            self._focus_widget("#dashboard_list", "main")

    def _focus_next_pane(self, delta: int) -> None:
        panes = [("#sidebar_list", "sidebar"), ("#dashboard_list", "main")]
        if self._search_items:
            panes.append(("#search_list", "search results"))
        panes.append(("#chat_input", "chat"))

        focused_id = self.focused.id if self.focused else ""
        ids = [selector.removeprefix("#") for selector, _label in panes]
        try:
            idx = ids.index(focused_id)
        except ValueError:
            idx = 1
        selector, label = panes[(idx + delta) % len(panes)]
        self._focus_widget(selector, label)

    def _move_list_cursor(self, delta: int) -> bool:
        focused = self.focused
        if not isinstance(focused, ListView):
            return False
        if not focused.children:
            return True

        start = focused.index if focused.index is not None else 0
        idx = start
        total = len(focused.children)
        for _ in range(total):
            idx = (idx + delta) % total
            child = focused.children[idx]
            if not getattr(child, "disabled", False):
                focused.index = idx
                if focused.id == "sidebar_list" and child.name in SIDEBAR_ITEMS:
                    self.current_tab = child.name
                    self._clear_search_results()
                    self.refresh_dashboard()
                    self._announce_navigation()
                return True
        return True

    def _move_list_edge(self, end: bool = False) -> bool:
        focused = self.focused
        if not isinstance(focused, ListView) or not focused.children:
            return False
        indexes = range(len(focused.children) - 1, -1, -1) if end else range(len(focused.children))
        for idx in indexes:
            child = focused.children[idx]
            if not getattr(child, "disabled", False):
                focused.index = idx
                if focused.id == "sidebar_list" and child.name in SIDEBAR_ITEMS:
                    self.current_tab = child.name
                    self._clear_search_results()
                    self.refresh_dashboard()
                    self._announce_navigation()
                return True
        return True

    def _activate_focused_list_item(self) -> bool:
        focused = self.focused
        if not isinstance(focused, ListView):
            return False
        item = focused.highlighted_child
        if item:
            self._activate_list_item(focused, item)
        return True

    def _select_tab(self, name: str) -> None:
        self.current_tab = name
        self._clear_search_results()
        self.refresh_dashboard()
        self._announce_navigation()
        self._focus_widget("#dashboard_list", name.lower())

    def _handle_g_command(self, key: str) -> bool:
        commands = {
            "g": lambda: self._move_list_edge(False),
            "G": lambda: self._move_list_edge(True),
            "h": lambda: self._focus_widget("#sidebar_list", "sidebar"),
            "m": lambda: self._focus_widget("#dashboard_list", "main"),
            "s": self._focus_search_or_main,
            "c": lambda: self._focus_widget("#chat_input", "chat"),
            "n": lambda: self._select_tab("Notes"),
            "j": lambda: self._select_tab("Journals"),
            "t": lambda: self._select_tab("Tasks"),
            "a": lambda: self._select_tab("Archive"),
            "u": lambda: self._select_tab("Home"),
        }
        handler = commands.get(key)
        if not handler:
            self._set_status(f"unknown g command: g{key}")
            return True
        handler()
        return True

    def action_focus_main(self) -> None:
        self._focus_widget("#dashboard_list", "main")

    def _open_cmd(self, prefill: str = "") -> None:
        cmd = self.query_one("#cmd", Input)
        self._cmd_submit_prefix = ""
        cmd.placeholder = "Type a command"
        cmd.value = prefill
        self.set_focus(cmd)
        cmd.cursor_position = len(cmd.value)
        self.mode = Mode.SEARCH if prefill.startswith("search") else Mode.COMMAND
        self._update_mode_badge()

    def _open_new_note_prompt(self) -> None:
        if self.current_tab == "Notes":
            cmd = self.query_one("#cmd", Input)
            self._cmd_submit_prefix = "new note "
            cmd.placeholder = "folder/name"
            cmd.value = ""
            self.set_focus(cmd)
            cmd.cursor_position = 0
            self.mode = Mode.COMMAND
            self._update_mode_badge()
            self._set_status("new note: type folder/name and press enter")
        else:
            self._open_cmd("new note ")

    def _switch_tab(self, delta: int) -> None:
        self._pending_delete = None
        idx = SIDEBAR_ITEMS.index(self.current_tab)
        self.current_tab = SIDEBAR_ITEMS[(idx + delta) % len(SIDEBAR_ITEMS)]
        self._clear_search_results()
        self.refresh_dashboard()
        self._announce_navigation()

    def on_key(self, event: events.Key) -> None:
        focused = self.focused

        if isinstance(focused, Input) and focused.id == "cmd":
            if event.key == "escape":
                focused.value = ""
                self._cmd_prefix = ""
                self._cmd_submit_prefix = ""
                focused.placeholder = "Type a command"
                self._key_prefix = None
                self.mode = Mode.NORMAL
                self._update_mode_badge()
                self.set_focus(self.query_one("#dashboard_list", ListView))
                event.prevent_default()
            elif event.key == "tab":
                current = focused.value.lstrip(":;")
                matches = [c for c in COMMANDS if c.startswith(current) and c != current]
                if matches:
                    focused.value = matches[0]
                    focused.cursor_position = len(focused.value)
                event.prevent_default()
            return

        if isinstance(focused, Input) and focused.id == "chat_input":
            if event.key == "escape":
                self._key_prefix = None
                self.mode = Mode.NORMAL
                self._update_mode_badge()
                self.set_focus(self.query_one("#dashboard_list", ListView))
                event.prevent_default()
            return

        if isinstance(focused, Input):
            if event.key == "escape":
                focused.value = ""
                self._key_prefix = None
                self.set_focus(self.query_one("#dashboard_list", ListView))
                event.prevent_default()
            return

        key = event.key
        if key == "escape":
            self._key_prefix = None
            if self._search_items:
                self._clear_search_results()
            self._set_status("normal")
            event.prevent_default()
            return

        if self._key_prefix == "g":
            self._key_prefix = None
            self._handle_g_command(key)
            event.prevent_default()
            return

        if key == "g":
            self._key_prefix = "g"
            self._set_status("g...")
            event.prevent_default()
            return

        if key in {"colon", "semicolon", ":", ";"}:
            self._key_prefix = None
            self._open_cmd(":")
            event.prevent_default()
        elif key in {"slash", "/"}:
            self._key_prefix = None
            self._open_cmd("search ")
            event.prevent_default()
        elif key in {"down", "j"}:
            self._key_prefix = None
            self._move_list_cursor(1)
            event.prevent_default()
        elif key in {"up", "k"}:
            self._key_prefix = None
            self._move_list_cursor(-1)
            event.prevent_default()
        elif key == "G":
            self._key_prefix = None
            self._move_list_edge(True)
            event.prevent_default()
        elif key in {"left", "h"}:
            self._key_prefix = None
            self._focus_next_pane(-1)
            event.prevent_default()
        elif key in {"right", "l"}:
            self._key_prefix = None
            self._focus_next_pane(1)
            event.prevent_default()
        elif key in {"enter", "o"}:
            self._key_prefix = None
            self._activate_focused_list_item()
            event.prevent_default()
        elif key == "x":
            self._key_prefix = None
            self.action_toggle_task()
            event.prevent_default()
        elif key == "d":
            self._key_prefix = None
            self.action_delete_note()
            event.prevent_default()
        elif key == "t":
            self._key_prefix = None
            self.open_in_editor(notes_fs.ensure_today_journal())
            event.prevent_default()
        elif key == "n":
            self._key_prefix = None
            self._open_new_note_prompt()
            event.prevent_default()
        elif key == "c":
            self._key_prefix = None
            self._focus_widget("#chat_input", "chat")
            event.prevent_default()


def run() -> None:
    config.ensure_dirs()
    PKBApp(ansi_color=True).run()
