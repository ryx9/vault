"""Dashboard, sidebar, and search-result rendering."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from textual.widgets import Label, ListItem, ListView, Static

import config
import db
import notes as notes_fs
import parser
import retriever
import tasks
from ui_constants import SIDEBAR_ICONS, SIDEBAR_ITEMS, fmt_task


class DashboardViewsMixin:
    current_tab: str
    _task_items: list[tasks.Task]
    _search_items: list[retriever.Result]

    def refresh_dashboard(self) -> None:
        today = date.today()
        db.sync_tasks()
        counts = db.task_counts()
        n_notes = len([
            f for f in parser.iter_markdown_files(config.NOTES_DIR)
            if config.JOURNAL_DIR not in f.parents
        ])
        n_journals = len(parser.iter_markdown_files(config.JOURNAL_DIR))
        open_t = counts["open"]
        done_t = counts["done"]
        self.query_one("#header", Static).update(
            f"[bold]PKB[/bold]  ·  {today.strftime('%A, %-d %B %Y')}  ·  "
            f"{n_notes} notes  ·  {n_journals} journals  ·  "
            f"[{'yellow' if open_t else 'dim'}]{open_t} open[/{'yellow' if open_t else 'dim'}]"
            f" / [dim]{done_t} done[/dim] tasks"
        )
        self._update_mode_badge()
        self._populate_sidebar()
        self._populate_dashboard()

    def _populate_sidebar(self) -> None:
        counts = db.task_counts()
        sb = self.query_one("#sidebar_list", ListView)
        sb.clear()
        for name in SIDEBAR_ITEMS:
            icon = SIDEBAR_ICONS.get(name, " ")
            label = f" {icon}  {name}"
            if name == "Tasks" and counts["open"]:
                label += f"  [yellow]{counts['open']}[/yellow]"
            item = ListItem(Static(label), name=name)
            if name == self.current_tab:
                item.add_class("nav-active")
            sb.append(item)
        try:
            sb.index = SIDEBAR_ITEMS.index(self.current_tab)
        except ValueError:
            sb.index = 0

    def _populate_dashboard(self) -> None:
        self.query_one("#dashboard_title", Label).update(
            f"{SIDEBAR_ICONS.get(self.current_tab, '')}  {self.current_tab}"
        )
        dispatch = {
            "Home": self._populate_home_dashboard,
            "Tasks": self._populate_tasks_view,
            "Notes": self._populate_notes_view,
            "Journals": self._populate_journals_view,
            "Archive": self._populate_archive_view,
        }
        dispatch.get(self.current_tab, self._populate_tags_view)()

    def _recent_notes(self, count: int = 5) -> list[Path]:
        notes = [
            p for p in parser.iter_markdown_files(config.NOTES_DIR)
            if config.JOURNAL_DIR not in p.parents
        ]
        notes.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return notes[:count]

    def _recent_journals(self, count: int = 5) -> list[Path]:
        return notes_fs.list_journals(limit=count)

    def _section(self, dash: ListView, title: str) -> None:
        dash.append(ListItem(Static(f"[dim]-- {title} --[/dim]"), disabled=True))

    def _populate_home_dashboard(self) -> None:
        dash = self.query_one("#dashboard_list", ListView)
        dash.clear()
        counts = db.task_counts()

        due_today = [t for t in db.load_tasks(include_done=False) if t.due_date == date.today()]
        if due_today:
            self._section(dash, "due today")
            for task in due_today:
                dash.append(ListItem(Static(fmt_task(task)), name=f"{task.source_path}:{task.line_num}"))
        else:
            self._section(dash, f"tasks  {counts['open']} open · {counts['done']} done")
            dash.append(ListItem(Static("[dim]no tasks due today[/dim]"), disabled=True))

        self._section(dash, "recent notes")
        for path in self._recent_notes():
            dash.append(ListItem(Static(parser.relative_path(path)), name=parser.relative_path(path)))

        self._section(dash, "recent journals")
        for path in self._recent_journals():
            dash.append(ListItem(Static(parser.relative_path(path)), name=str(path)))

    def _populate_tasks_view(self) -> None:
        all_tasks = db.load_tasks(include_done=False)
        groups = tasks.group_tasks(all_tasks)
        self._task_items = all_tasks
        dash = self.query_one("#dashboard_list", ListView)
        dash.clear()
        for title, items in [
            ("due today", groups["due_today"]),
            ("upcoming", groups["upcoming"]),
            ("no due date", groups["no_date"]),
        ]:
            self._section(dash, title)
            if not items:
                dash.append(ListItem(Static("[dim]none[/dim]"), disabled=True))
            for task in items:
                dash.append(ListItem(Static(fmt_task(task)), name=f"{task.source_path}:{task.line_num}"))

    def _populate_notes_view(self) -> None:
        dash = self.query_one("#dashboard_list", ListView)
        dash.clear()
        notes = self._recent_notes(count=20)
        if not notes:
            dash.append(ListItem(Static("[dim]no notes found[/dim]"), disabled=True))
            return
        self._section(dash, "recent notes")
        for path in notes:
            rel = parser.relative_path(path)
            dash.append(ListItem(Static(rel), name=rel))

    def _populate_journals_view(self) -> None:
        dash = self.query_one("#dashboard_list", ListView)
        dash.clear()
        journals = notes_fs.list_journals(limit=20)
        if not journals:
            dash.append(ListItem(Static("[dim]no journal entries found[/dim]"), disabled=True))
            return
        self._section(dash, "journals")
        for path in journals:
            dash.append(ListItem(Static(parser.relative_path(path)), name=str(path)))

    def _populate_archive_view(self) -> None:
        dash = self.query_one("#dashboard_list", ListView)
        dash.clear()
        archive_dir = getattr(config, "ARCHIVE_DIR", None)
        if not archive_dir or not archive_dir.exists():
            dash.append(ListItem(Static("[dim]archive folder is empty or not configured[/dim]"), disabled=True))
            return
        archive_files = sorted(parser.iter_markdown_files(archive_dir), reverse=True)
        if not archive_files:
            dash.append(ListItem(Static("[dim]no archived notes[/dim]"), disabled=True))
            return
        self._section(dash, "archive")
        for path in archive_files:
            dash.append(ListItem(Static(parser.relative_path(path)), name=parser.relative_path(path)))

    def _populate_tags_view(self) -> None:
        dash = self.query_one("#dashboard_list", ListView)
        dash.clear()
        self._section(dash, "tags")
        dash.append(ListItem(Static("[dim]tag support coming soon[/dim]"), disabled=True))

    def _populate_search_results(self, results: list[retriever.Result]) -> None:
        self._search_items = results
        sl = self.query_one("#search_list", ListView)
        bar = self.query_one("#search_results_bar", Static)
        sl.clear()

        if not results:
            sl.remove_class("has-results")
            bar.remove_class("visible")
            bar.update("")
            return

        sl.add_class("has-results")
        bar.add_class("visible")
        bar.update(f"[dim]search results - {len(results)} found · enter to open · Esc to clear[/dim]")

        for result in results:
            heading = f" - {result.heading}" if result.heading else ""
            snippet = result.text.strip().replace("\n", " ")[:72]
            sl.append(ListItem(
                Static(f"{result.path}{heading}\n  [dim]{snippet}[/dim]"),
                name=result.path,
            ))

    def _clear_search_results(self) -> None:
        sl = self.query_one("#search_list", ListView)
        bar = self.query_one("#search_results_bar", Static)
        sl.clear()
        sl.remove_class("has-results")
        bar.remove_class("visible")
        bar.update("")
        self._search_items = []
