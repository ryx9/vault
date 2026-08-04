#.pkb — Terminal Personal Knowledge Base

A live dashboard + hybrid search + optional RAG layer over a folder of
Markdown notes. Markdown is the only source of truth; everything else
(`.pkb/`) is a disposable, regenerable cache.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and `nvim` on your `$PATH`.

```bash
uv sync
cp .env.example .env   # optional — for ask/LLM
```

API keys and config live in `.env` (gitignored). The app loads them via
`python-dotenv` when you run through uv.

## Run

```bash
uv run.pkb
# or
uv run python app.py
```

On first launch, `notes/`, `.pkb/`, and today's journal are created
automatically.

## Dashboard

Three panels:

- **Notes & Folders** — tree of everything under `notes/` (except
  `journal/`). Click a note to open it in nvim.
- **Journals** — recent daily journals; today's entry is marked with ★.
- **Tasks** — open tasks grouped by due date. Press **x** or select a
  task to toggle done.
- **Search** — results from `search <query>`; select to open.

### Commands (bottom input bar)

| Command | Action |
|---|---|
| `search <q>` | Hybrid search; results appear in the Search panel |
| `ask <q>` | RAG Q&A (needs `OPENROUTER_API_KEY` in `.env`) |
| `new note <name>` | Create a note (`folder/name` for subfolders) |
| `new journal [YYYY-MM-DD]` | Create/open a journal |
| `new folder <name>` | Create a folder under `notes/` |
| `open <path>` | Open a note in nvim |
| `done <path>:<line>` | Mark a task done/open |
| `today` | Open today's journal |
| `tasks` | Full task list in the output bar |
| `reindex` | Rebuild search + embeddings cache |
| `quit` | Exit |

### Keyboard shortcuts

| Key | Action |
|---|---|
| `Ctrl+Q` | Quit |
| `Ctrl+1` | Focus sidebar |
| `Ctrl+2` | Focus main list |
| `Ctrl+3` | Focus chat input |
| `j` / `k` or `↓` / `↑` | Move selection inside the focused list |
| `h` / `l` or `←` / `→` | Move focus between panes: sidebar, main, search results, chat |
| `gg` / `G` | Jump to the top / bottom of the focused list |
| `Enter` or `o` | Open/activate the selected row |
| `gh` / `gm` / `gs` / `gc` | Focus sidebar / main / search results / chat |
| `gu` / `gt` / `gn` / `gj` / `ga` | Open Home / Tasks / Notes / Journals / Archive |
| `x` | Toggle selected task done/open |
| `d` | Delete the selected note/journal; press `d` again to confirm |
| `:` or `;` | Focus an empty command bar |
| `/` | Focus command bar with `search ` prefilled |
| `n` | Start a new note prompt; in Notes, type `folder/name` and press Enter |
| `t` | Open today's journal |
| `c` | Focus chat input |
| `Esc` | Leave command/chat input, or clear search results |

Navigation feedback is intentionally lightweight: the selected sidebar row
uses a visible active style, the dashboard title changes to the selected view,
focused panes use an accent border, and view/focus changes update the footer
status line.

Deleting a note from the TUI removes the markdown file and clears derived
keyword-search and embedding cache rows for that path.

## Tasks

Write tasks anywhere in markdown:

```markdown
TODO: buy milk tomorrow
TODO: X finished task
```

A leading **X** after `TODO:` means done. Toggle from the UI writes the
marker back to the file. Task state is mirrored in `.pkb/meta.db` (SQLite)
and resynced on every file change.

## Optional LLM (`ask`)

Set in `.env`:

```bash
GEMINI_API_KEY=...
PKB_LLM_MODEL=gemini-3.5-pro
```

If you prefer OpenRouter fallback, `OPENROUTER_API_KEY` with `PKB_LLM_MODEL=google/gemma-3-12b-it:free` still works.

`ask` always retrieves relevant chunks first and works with **no LLM
configured** — it just shows retrieved notes.

## Module map

| File | Responsibility |
|---|---|
| `config.py` | paths, constants, `.env` loading |
| `parser.py` | markdown → headings / chunks / TODO lines |
| `tasks.py` | TODO lines → dated tasks |
| `db.py` | SQLite task sync (`.pkb/meta.db`) |
| `notes.py` | create notes, folders, journals |
| `embeddings.py` | sentence-transformers + ChromaDB |
| `search.py` | SQLite FTS5 keyword index |
| `retriever.py` | merges keyword + fuzzy + semantic search |
| `watcher.py` | incremental reindex on file save |
| `llm.py` | optional OpenRouter for `ask` |
| `ui.py` | Textual app shell, focus, navigation, chat lifecycle |
| `ui_styles.py` | terminal-theme-aware Textual CSS |
| `ui_constants.py` | UI modes, command completions, sidebar labels |
| `ui_views.py` | sidebar, dashboard, and search-result rendering |
| `ui_commands.py` | command-bar parsing and command implementations |
| `app.py` | entry point |

## Notes

- First run downloads the `BAAI/bge-small-en-v1.5` embedding model
  (~130MB) from Hugging Face — needs internet once, then cached locally.
- Delete `.pkb/` any time and run `reindex` to rebuild from `notes/`.
