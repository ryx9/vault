"""Filesystem helpers for notes, folders, and journals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import config
import embeddings
import parser
import search

JOURNAL_TEMPLATE = "# Journal — {date}\n\n## Notes\n\n## Tasks\n\n"
NOTE_TEMPLATE = "# {title}\n\n"


@dataclass
class BrowseNode:
    """Folder node in the notes tree (excludes journal/)."""

    name: str
    rel_path: str
    notes: list[str] = field(default_factory=list)
    folders: list[BrowseNode] = field(default_factory=list)


def journal_path_for(day: date) -> Path:
    return config.JOURNAL_DIR / f"{day.isoformat()}.md"


def ensure_today_journal() -> Path:
    return ensure_journal(date.today())


def ensure_journal(day: date) -> Path:
    path = journal_path_for(day)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(JOURNAL_TEMPLATE.format(date=day.isoformat()), encoding="utf-8")
        search.index_file(path)
        if config.ENABLE_SEMANTIC_SEARCH:
            embeddings.reindex_file(path)
    return path


SAMPLE_NOTES = {
    "welcome.md": "# Welcome to PKB\n\nThis is your personal knowledge base. Use `new note <name>` to add ideas, meeting notes, or journaling.\n\n## Search\n\nSearch works across filenames, headings, bodies, and TODOs.\n\nTODO: try search for 'welcome' or 'note'\n",
    "ideas.md": "# Project Ideas\n\n- Add a note graph view\n- Track book summaries\n- Build a better search panel\n\nTODO: refine sample content\n",
    "recipes.md": "# Recipes\n\n## Pancakes\n\nIngredients:\n- flour\n- milk\n- eggs\n\nInstructions:\n1. Mix everything.\n2. Cook on a hot pan.\n",
}


def ensure_sample_notes() -> None:
    existing = {
        path.name
        for path in parser.iter_markdown_files(config.NOTES_DIR)
        if config.JOURNAL_DIR not in path.parents
    }

    for filename, content in SAMPLE_NOTES.items():
        if filename in existing:
            continue
        path = config.NOTES_DIR / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        search.index_file(path)
        if config.ENABLE_SEMANTIC_SEARCH:
            embeddings.reindex_file(path)


def list_journals(limit: int | None = None) -> list[Path]:
    files = sorted(parser.iter_markdown_files(config.JOURNAL_DIR), reverse=True)
    return files[:limit] if limit else files


def build_browse_tree() -> BrowseNode:
    """Build a folder tree of notes, excluding the journal directory."""
    root = BrowseNode(name="notes", rel_path="")

    def scan_dir(directory: Path, node: BrowseNode) -> None:
        if not directory.exists():
            return
        for child in sorted(directory.iterdir()):
            if not child.is_dir():
                continue
            if child.resolve() == config.JOURNAL_DIR.resolve():
                continue
            rel = parser.relative_path(child)
            folder = BrowseNode(name=child.name, rel_path=rel)
            node.folders.append(folder)
            scan_dir(child, folder)

        for md in sorted(directory.glob("*.md")):
            node.notes.append(parser.relative_path(md))

    scan_dir(config.NOTES_DIR, root)
    return root


def create_folder(name: str, parent: str = "") -> Path:
    folder = config.NOTES_DIR / parent / name if parent else config.NOTES_DIR / name
    folder.mkdir(parents=True, exist_ok=False)
    return folder


def create_note(name: str, folder: str = "") -> Path:
    stem = name if name.endswith(".md") else f"{name}.md"
    path = config.NOTES_DIR / folder / stem if folder else config.NOTES_DIR / stem
    if path.exists():
        raise FileExistsError(f"Note already exists: {parser.relative_path(path)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    title = stem.removesuffix(".md").replace("-", " ").replace("_", " ").title()
    path.write_text(NOTE_TEMPLATE.format(title=title), encoding="utf-8")
    search.index_file(path)
    if config.ENABLE_SEMANTIC_SEARCH:
        embeddings.reindex_file(path)
    return path


def resolve_note_path(spec: str) -> Path | None:
    """Resolve a user-provided path spec to an existing note."""
    candidate = config.NOTES_DIR / spec
    if candidate.suffix != ".md":
        candidate = candidate.with_suffix(".md")
    return candidate if candidate.is_file() else None


def delete_note(path: Path) -> str:
    """Delete a note and remove its derived search and embedding cache rows."""
    resolved = path.resolve()
    notes_root = config.NOTES_DIR.resolve()
    if notes_root not in resolved.parents:
        raise ValueError("refusing to delete a file outside notes/")
    if not path.is_file() or path.suffix != ".md":
        raise FileNotFoundError(path)

    rel = parser.relative_path(path)
    search.remove_file(rel)
    embeddings.remove_file_embeddings(rel)
    path.unlink()
    return rel
