"""True Gemini agent using native function calling.

Architecture:
  1. Hybrid retrieval runs first (fast, free, no LLM tokens).
  2. Retrieved chunks + tool schemas are sent to Gemini.
  3. Agent loop: if the model returns a functionCall, execute it and feed the
     result back; repeat until the model returns plain text.

Requires the `google-genai` SDK:
    pip install google-genai

Falls back to OpenRouter (OpenAI-compatible) with a simpler single-pass
approach when GEMINI_API_KEY is absent.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

import config
import notes as notes_fs
import parser
import retriever
import search
import tasks

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy SDK import — only needed when GEMINI_API_KEY is set
# ---------------------------------------------------------------------------


def _gemini_client():
    """Return a configured Gemini GenerativeModel (google-genai SDK)."""
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore  # noqa: F401
    except ImportError as exc:
        raise ImportError("google-genai is required: pip install google-genai") from exc

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    return client


# ---------------------------------------------------------------------------
# Tool registry — single source of truth for schemas AND implementations
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "search_notes",
        "description": (
            "Full-text keyword search across all personal notes. "
            "Use this to discover which notes are relevant before reading them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "top_k": {
                    "type": "integer",
                    "description": "Maximum results to return (default 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_journals",
        "description": (
            "Full-text search restricted to journal / diary entries only. "
            "Prefer this over search_notes when the question is about personal "
            "experiences, daily events, or dated entries."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "top_k": {
                    "type": "integer",
                    "description": "Maximum results to return (default 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_note",
        "description": (
            "Read the full contents of a single note or journal entry by path. "
            "Use after search_notes / search_journals to retrieve the full text "
            "of a promising result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the note, e.g. projects/work.md",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_tasks",
        "description": (
            "List all tasks / to-dos extracted from notes. "
            "Use when the question is about deadlines, upcoming work, or pending items."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "include_done": {
                    "type": "boolean",
                    "description": "Whether to include completed tasks (default false)",
                },
            },
            "required": [],
        },
    },
]


def _resolve_note_path(spec: str) -> str | None:
    """Resolve a fuzzy path spec to a vault-relative path string, or None."""
    candidate = spec.strip()
    if not candidate:
        return None
    resolved = notes_fs.resolve_note_path(candidate)
    if resolved:
        return parser.relative_path(resolved)
    if candidate.startswith("journal/") or candidate.endswith(".md"):
        return candidate
    return None


def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a tool call and return a JSON-serialisable result dict."""
    tool_name = (name or "").strip().lower()

    if tool_name == "search_notes":
        query = str(args.get("query", "")).strip()
        if not query:
            return {"success": False, "error": "query is required"}
        results = search.keyword_search(query, top_k=int(args.get("top_k", 5)))
        return {
            "success": True,
            "tool": "search_notes",
            "query": query,
            "results": results,
        }

    if tool_name == "search_journals":
        query = str(args.get("query", "")).strip()
        if not query:
            return {"success": False, "error": "query is required"}
        results = search.keyword_search(query, top_k=int(args.get("top_k", 5)))
        journal_results = [
            r for r in results if str(r.get("path", "")).startswith("journal/")
        ]
        return {
            "success": True,
            "tool": "search_journals",
            "query": query,
            "results": journal_results,
        }

    if tool_name == "read_note":
        spec = str(args.get("path", "")).strip()
        resolved = _resolve_note_path(spec)
        if not resolved:
            return {"success": False, "error": f"note not found: {spec}"}

        if resolved.startswith("journal/"):
            path = config.JOURNAL_DIR / resolved.split("/", 1)[1]
        else:
            path = config.NOTES_DIR / resolved

        if not path.exists():
            return {"success": False, "error": f"note not found: {resolved}"}

        content = parser.read_file(path)
        return {
            "success": True,
            "tool": "read_note",
            "path": resolved,
            "content": content,
        }

    if tool_name == "list_tasks":
        include_done = bool(args.get("include_done", False))
        task_list = []
        for task in tasks.extract_all_tasks(include_done=include_done):
            task_list.append(
                {
                    "title": task.title,
                    "due_date": task.due_date.isoformat() if task.due_date else None,
                    "source_path": task.source_path,
                    "line_num": task.line_num,
                    "done": task.done,
                }
            )
        return {"success": True, "tool": "list_tasks", "results": task_list}

    return {"success": False, "error": f"unknown tool: {name}"}


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------


def _expand_chunks_with_graph(chunks: list[retriever.Result]) -> list[retriever.Result]:
    """Follow one hop of wiki-links to pull in referenced notes."""
    seen = {c.path for c in chunks}
    extras: list[retriever.Result] = []
    for chunk in chunks[:6]:
        for ref in parser.extract_references_from_text(
            chunk.text, base_path=chunk.path
        ):
            if ref in seen:
                continue
            path = config.NOTES_DIR / ref
            if not path.exists():
                continue
            for rc in parser.chunk_markdown(path):
                if rc.text.strip():
                    extras.append(
                        retriever.Result(
                            path=rc.path, heading=rc.heading, text=rc.text, score=0.0
                        )
                    )
            seen.add(ref)
    return chunks + extras


def _chunks_to_context(chunks: list[retriever.Result]) -> str:
    blocks = []
    for i, c in enumerate(chunks, 1):
        label = f"[{i}] {c.path}" + (f" — {c.heading}" if c.heading else "")
        blocks.append(f"{label}\n{c.text}")
    return "\n\n".join(blocks)


# ---------------------------------------------------------------------------
# Gemini agent loop
# ---------------------------------------------------------------------------

MAX_AGENT_TURNS = 10  # hard cap to prevent infinite loops

_SYSTEM_PROMPT = (
    "You are a helpful personal notes assistant. "
    "You have access to the user's notes vault through the provided tools. "
    "Always search or read notes before answering factual questions about the vault. "
    "Cite every note you draw on using its path in brackets, e.g. [projects/work.md]. "
    "If the notes don't contain the answer, say so honestly — never invent facts. "
    "Answer directly and concisely. Do not reveal your reasoning, do not narrate your process, and do not explain what you are thinking."
)


def _run_gemini_agent(
    question: str,
    chunks: list[retriever.Result],
    history: list[dict] | None,
) -> str:
    """Run the Gemini native function-calling agent loop."""
    try:
        from google import genai  # type: ignore
        from google.genai import types  # type: ignore
    except ImportError as exc:
        raise ImportError("pip install google-genai") from exc

    client = _gemini_client()

    # Build the initial user message, seeding it with retrieved chunks so the
    # model can answer simple questions without any tool calls.
    context_section = ""
    if chunks:
        context_section = f"\n\nPRE-RETRIEVED NOTES (use these if sufficient):\n{_chunks_to_context(chunks)}\n"

    user_content = f"{context_section}\nQUESTION: {question}"

    # Convert history to Gemini Content objects
    contents: list[types.Content] = []
    if history:
        for msg in history:
            role = "user" if msg.get("role") == "user" else "model"
            contents.append(
                types.Content(
                    role=role, parts=[types.Part(text=msg.get("content", ""))]
                )
            )
    contents.append(types.Content(role="user", parts=[types.Part(text=user_content)]))

    # Declare tools to Gemini
    tool_declarations = [
        types.FunctionDeclaration(
            name=s["name"],
            description=s["description"],
            parameters=s["parameters"],
        )
        for s in TOOL_SCHEMAS
    ]
    gemini_tools = [types.Tool(function_declarations=tool_declarations)]

    # ---- Agent loop --------------------------------------------------------
    for turn in range(MAX_AGENT_TURNS):
        response = client.models.generate_content(
            model=getattr(config, "GEMINI_MODEL", "gemini-2.5-flash"),
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_PROMPT,
                tools=gemini_tools,
                temperature=0.2,
                max_output_tokens=2048,
            ),
        )

        candidate = response.candidates[0]
        parts = candidate.content.parts or []

        # Collect all function calls in this response
        function_calls = [
            p.function_call
            for p in parts
            if getattr(p, "function_call", None) is not None
        ]

        # Filter out internal thought parts from text output
        text_parts = [
            p
            for p in parts
            if getattr(p, "text", None) and not getattr(p, "thought", False)
        ]

        if not function_calls:
            # Model returned a final text answer — we're done
            return "".join(p.text for p in text_parts).strip()

        # Add the model's turn (which contains the function calls) to history
        contents.append(types.Content(role="model", parts=parts))

        # Execute every function call and collect results
        tool_response_parts: list[types.Part] = []
        for fc in function_calls:
            args = dict(fc.args) if getattr(fc, "args", None) else {}
            log.debug("Tool call: %s(%s)", fc.name, args)
            result = execute_tool(fc.name, args)
            log.debug("Tool result: %s", result)
            tool_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": json.dumps(result, default=str)},
                    )
                )
            )

        # Feed all results back in a single user turn
        contents.append(types.Content(role="user", parts=tool_response_parts))

    # Fallback if we hit the turn limit
    log.warning(
        "Agent hit MAX_AGENT_TURNS (%d) without a final answer.", MAX_AGENT_TURNS
    )
    return (
        "(Agent reached the maximum number of reasoning steps without a final answer.)"
    )


# ---------------------------------------------------------------------------
# OpenRouter fallback (single-pass, no native function calling)
# ---------------------------------------------------------------------------

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _run_openrouter(
    question: str,
    chunks: list[retriever.Result],
    history: list[dict] | None,
) -> str:
    context = _chunks_to_context(chunks) if chunks else "(no notes retrieved)"
    prompt = (
        "You are a helpful personal notes assistant. Use only the notes below.\n"
        "Cite every note you use as [path/to/note.md].\n"
        "If the notes don't contain the answer, say so.\n\n"
        f"NOTES:\n{context}\n\nQUESTION: {question}"
    )
    messages = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
        json={
            "model": config.OPENROUTER_MODEL,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 1024,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _configured_backends() -> list[str]:
    backends: list[str] = []
    if getattr(config, "GEMINI_API_KEY", None):
        backends.append("gemini")
    if getattr(config, "OPENROUTER_API_KEY", None):
        backends.append("openrouter")
    return backends


def is_configured() -> bool:
    return bool(_configured_backends())


def backend_label() -> str:
    backend = _configured_backends()
    if backend and backend[0] == "gemini":
        return "Gemini"
    if backend and backend[0] == "openrouter":
        return "OpenRouter"
    return "None"


def ask(question: str, top_k: int = 6, history: list[dict] | None = None) -> dict:
    """Entry point.

    Returns::

        {
            "answer": str | None,   # None when no LLM is configured
            "chunks": [Result],     # raw retrieval results (always present)
        }

    When a Gemini key is present the full agent loop runs.
    When only an OpenRouter key is present a single-pass call is made.
    When neither key is present, raw chunks are returned for the caller to render.
    """
    # 1. Retrieval (always runs — fast, no tokens)
    chunks = retriever.hybrid_search(question, top_k=top_k)
    chunks = _expand_chunks_with_graph(chunks)

    backends = _configured_backends()
    if not backends:
        return {"answer": None, "chunks": chunks}

    last_error: Exception | None = None
    for backend in backends:
        try:
            if backend == "gemini":
                answer = _run_gemini_agent(question, chunks, history)
            else:
                answer = _run_openrouter(question, chunks, history)
            return {"answer": answer, "chunks": chunks}
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            log.exception("LLM call failed via %s", backend)
            if backend == "gemini" and "openrouter" in backends:
                continue

    if last_error is not None:
        answer = f"(LLM request failed: {last_error}. Showing retrieved notes instead.)"
    else:
        answer = None

    return {"answer": answer, "chunks": chunks}
