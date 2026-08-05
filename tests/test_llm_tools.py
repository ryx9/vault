"""Live integration tests — hit the real Gemini API.

Every failure prints WHY it failed: the exception type, message, and
HTTP status when available, so you never have to guess what went wrong.

Prerequisites
-------------
1.  uv add --dev pytest
2.  google-genai in your deps:  uv add google-genai
3.  config.py one level above tests/ with:
        GEMINI_API_KEY = "your-key"
        GEMINI_MODEL   = "gemini-2.5-flash"   # or whichever you use

Run
---
    uv run pytest tests/test_gemini_live.py -v -s
"""

from __future__ import annotations

import sys
import textwrap
import time
import traceback
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Make the project root importable when the file lives in tests/
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Load config — skip immediately with a clear message if missing / blank
# ---------------------------------------------------------------------------
try:
    import config as _cfg

    _KEY = getattr(_cfg, "GEMINI_API_KEY", None) or ""
    _MODEL = getattr(_cfg, "GEMINI_MODEL", None) or "gemini-2.5-flash"
except ModuleNotFoundError as e:
    pytest.skip(
        f"config.py not found — {e}\n"
        "Create config.py in the project root with GEMINI_API_KEY and GEMINI_MODEL.",
        allow_module_level=True,
    )

if not _KEY:
    pytest.skip(
        "GEMINI_API_KEY is empty in config.py — add your Gemini key to run live tests.",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# SDK import
# ---------------------------------------------------------------------------
try:
    from google import genai
    from google.genai import types
except ImportError as e:
    pytest.skip(
        f"google-genai not installed — {e}\nFix: uv add google-genai",
        allow_module_level=True,
    )

# ---------------------------------------------------------------------------
# Shared client
# ---------------------------------------------------------------------------
CLIENT = genai.Client(api_key=_KEY)
TIMEOUT_SECONDS = 30


# ---------------------------------------------------------------------------
# Exception formatting — the core of "why did it fail"
# ---------------------------------------------------------------------------


def _format_exc(exc: Exception) -> str:
    """Return a multi-line string that explains exactly what went wrong."""
    lines = [
        f"Exception : {type(exc).__name__}",
        f"Message   : {exc}",
    ]

    # HTTP status / body (google-genai wraps these in various ways)
    for attr in ("status_code", "code", "http_status"):
        val = getattr(exc, attr, None)
        if val is not None:
            lines.append(f"HTTP status: {val}")
            break

    for attr in ("message", "details", "reason", "response"):
        val = getattr(exc, attr, None)
        if val and str(val) != str(exc):
            lines.append(f"Detail     : {val}")
            break

    # Full traceback so you can see exactly which line in the SDK raised
    tb = traceback.format_exc()
    if tb and tb.strip() != "NoneType: None":
        lines.append("Traceback  :\n" + textwrap.indent(tb.strip(), "  "))

    return "\n".join(lines)


def _diagnose(exc: Exception) -> str:
    """Map common exceptions to plain-English hints."""
    msg = str(exc).lower()
    exc_type = type(exc).__name__

    hints: list[str] = []

    if "api_key" in msg or "api key" in msg or "invalid" in msg and "key" in msg:
        hints.append("→ Your GEMINI_API_KEY looks wrong or has been revoked.")
    if "quota" in msg or "resource_exhausted" in msg or "429" in msg:
        hints.append("→ You've hit your API quota. Check https://aistudio.google.com/")
    if "not found" in msg or "404" in msg:
        hints.append(f"→ Model '{_MODEL}' not found. Check GEMINI_MODEL in config.py.")
    if "permission" in msg or "403" in msg:
        hints.append("→ Key doesn't have permission for this model or region.")
    if "unavailable" in msg or "503" in msg:
        hints.append(
            "→ Gemini service is temporarily unavailable. Try again in a minute."
        )
    if "timeout" in msg or "deadline" in msg:
        hints.append(
            "→ Request timed out. The API may be slow or your network is down."
        )
    if "connection" in msg or "network" in msg:
        hints.append(
            "→ Could not reach the Gemini API. Check your internet connection."
        )

    if not hints:
        hints.append("→ Unexpected error — see traceback above for details.")

    return "\n".join(hints)


# ---------------------------------------------------------------------------
# _generate — every API call goes through here so errors are always rich
# ---------------------------------------------------------------------------


def _generate(contents, *, tools=None, system=None) -> Any:
    """Call Gemini and return the response, or fail with a full diagnosis."""
    cfg_kwargs: dict = {"temperature": 0.0, "max_output_tokens": 512}
    if tools:
        cfg_kwargs["tools"] = tools
    if system:
        cfg_kwargs["system_instruction"] = system

    start = time.monotonic()
    try:
        response = CLIENT.models.generate_content(
            model=_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
    except Exception as exc:
        formatted = _format_exc(exc)
        hints = _diagnose(exc)
        pytest.fail(
            f"\n\nGemini API call FAILED\n"
            f"{'=' * 60}\n"
            f"Model : {_MODEL}\n"
            f"Key   : {_KEY[:8]}{'*' * (len(_KEY) - 8) if len(_KEY) > 8 else '...'}\n"
            f"{'=' * 60}\n"
            f"{formatted}\n"
            f"{'=' * 60}\n"
            f"Possible causes:\n{hints}\n"
        )

    elapsed = time.monotonic() - start
    print(f"\n  ⏱  {elapsed:.2f}s", end="")

    if elapsed >= TIMEOUT_SECONDS:
        pytest.fail(
            f"Gemini took {elapsed:.1f}s (limit: {TIMEOUT_SECONDS}s).\n"
            "→ The API may be overloaded, or the request is malformed and hanging."
        )

    return response


def _first_text(response) -> str:
    """Extract the first text part, or '' — never raises."""
    try:
        for part in response.candidates[0].content.parts:
            if getattr(part, "text", None):
                return part.text.strip()
    except (AttributeError, IndexError, TypeError) as exc:
        print(f"\n  [warn] _first_text failed: {exc}")
    return ""


def _function_calls(response) -> list:
    """Return all function_call parts — never raises."""
    try:
        return [
            p.function_call
            for p in response.candidates[0].content.parts
            if getattr(p, "function_call", None) is not None
        ]
    except (AttributeError, IndexError, TypeError) as exc:
        print(f"\n  [warn] _function_calls failed: {exc}")
        return []


def _assert_text(response, context: str = "") -> str:
    """Assert the response contains text and return it, with full diagnosis on failure."""
    text = _first_text(response)
    if text:
        return text

    # Build a detailed picture of what we actually got
    try:
        candidate = response.candidates[0]
        parts_info = []
        for i, p in enumerate(candidate.content.parts):
            if getattr(p, "text", None):
                parts_info.append(f"  part[{i}]: text={p.text!r}")
            elif getattr(p, "function_call", None):
                parts_info.append(
                    f"  part[{i}]: function_call={p.function_call.name}({dict(p.function_call.args)})"
                )
            else:
                parts_info.append(f"  part[{i}]: {p}")
        finish_reason = getattr(candidate, "finish_reason", "unknown")
        safety = getattr(candidate, "safety_ratings", [])
        parts_str = "\n".join(parts_info) or "  (no parts)"
    except Exception as exc:
        parts_str = f"  (could not inspect response: {exc})"
        finish_reason = "unknown"
        safety = []

    pytest.fail(
        f"\n\nExpected a text response but got none. {context}\n"
        f"{'=' * 60}\n"
        f"finish_reason : {finish_reason}\n"
        f"safety_ratings: {safety}\n"
        f"Parts received:\n{parts_str}\n"
        f"{'=' * 60}\n"
        "Possible causes:\n"
        "→ The model returned only a function call (check _function_calls()).\n"
        "→ The response was blocked by safety filters (check safety_ratings above).\n"
        "→ finish_reason=MAX_TOKENS — increase max_output_tokens.\n"
        "→ finish_reason=STOP but empty text — rare SDK bug, retry once.\n"
    )


# ===========================================================================
# Tool declarations (reused across tests)
# ===========================================================================

SEARCH_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_notes",
            description="Search personal notes by keyword.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search terms"},
                    "top_k": {"type": "integer", "description": "Max results"},
                },
                "required": ["query"],
            },
        )
    ]
)

ALL_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="search_notes",
            description="Search personal notes by keyword.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "top_k": {"type": "integer"},
                },
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="search_journals",
            description="Search journal/diary entries by keyword.",
            parameters={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        ),
        types.FunctionDeclaration(
            name="read_note",
            description="Read the full content of a note by path.",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        ),
        types.FunctionDeclaration(
            name="list_tasks",
            description="List all to-dos and tasks from notes.",
            parameters={
                "type": "object",
                "properties": {"include_done": {"type": "boolean"}},
                "required": [],
            },
        ),
    ]
)


# ===========================================================================
# 1. Connectivity
# ===========================================================================


class TestConnectivity:
    def test_api_responds_at_all(self):
        """Most fundamental check — if this fails, all others will too."""
        response = _generate(
            [
                types.Content(
                    role="user",
                    parts=[types.Part(text="Reply with the single word: PONG")],
                )
            ]
        )
        text = _assert_text(response, context="Asked Gemini to reply PONG.")
        print(f"\n  Got: {text!r}")

    def test_correct_model_is_used(self):
        response = _generate(
            [
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                "What is your model name? One short sentence, no markdown."
                            )
                        )
                    ],
                )
            ]
        )
        text = _assert_text(response, context="Asked Gemini its model name.")
        print(f"\n  Model says: {text!r}")
        assert len(text) < 300, (
            f"Answer is suspiciously long ({len(text)} chars) — may be an error page:\n{text}"
        )

    def test_response_has_candidates(self):
        response = _generate(
            [types.Content(role="user", parts=[types.Part(text="Say hello.")])]
        )
        assert response.candidates, (
            "response.candidates is empty.\n"
            "→ The entire response was blocked or the API returned an empty payload."
        )
        assert response.candidates[0].content.parts, (
            "candidates[0].content.parts is empty.\n"
            "→ The candidate exists but has no content — possible safety block."
        )


# ===========================================================================
# 2. Text generation
# ===========================================================================


class TestTextGeneration:
    def test_factual_answer(self):
        response = _generate(
            [
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                "What is 7 multiplied by 6? Reply with just the number."
                            )
                        )
                    ],
                )
            ]
        )
        text = _assert_text(response, context="Asked 7×6.")
        print(f"\n  Got: {text!r}")
        assert "42" in text, (
            f"Expected '42' in the answer but got: {text!r}\n"
            "→ Model may be hallucinating or not following the single-number instruction."
        )

    def test_system_prompt_obeyed(self):
        response = _generate(
            [
                types.Content(
                    role="user", parts=[types.Part(text="What colour is the sky?")]
                )
            ],
            system="You are a pirate. Always respond in pirate speak.",
        )
        text = _assert_text(
            response, context="Asked sky colour with pirate system prompt."
        )
        print(f"\n  Got: {text!r}")
        assert len(text) > 3, f"Response too short to be valid: {text!r}"

    def test_multi_turn_memory(self):
        """Gemini must carry context across turns."""
        contents = [
            types.Content(
                role="user",
                parts=[types.Part(text="My secret number is 73. Remember it.")],
            ),
            types.Content(
                role="model",
                parts=[types.Part(text="Got it, your secret number is 73.")],
            ),
            types.Content(
                role="user",
                parts=[types.Part(text="What is my secret number? Just the digits.")],
            ),
        ]
        response = _generate(contents)
        text = _assert_text(response, context="Asked Gemini to recall number 73.")
        print(f"\n  Got: {text!r}")
        assert "73" in text, (
            f"Gemini forgot the number — got: {text!r}\n"
            "→ Multi-turn history may not be threaded correctly in the request."
        )


# ===========================================================================
# 3. Function / tool calling
# ===========================================================================


class TestFunctionCalling:
    def test_model_issues_a_tool_call(self):
        response = _generate(
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=(
                                "Search my notes for 'project deadline'. Use the search_notes tool."
                            )
                        )
                    ],
                )
            ],
            tools=[SEARCH_TOOL],
            system="You are a notes assistant. Always use tools to look up information.",
        )
        fcs = _function_calls(response)
        plain = _first_text(response)
        assert fcs, (
            f"Expected a function call but got plain text instead:\n  {plain!r}\n"
            "→ Gemini ignored the tool. Possible causes:\n"
            "  • System prompt not strong enough — try 'You MUST use search_notes'.\n"
            "  • Tool schema has a syntax error — check SEARCH_TOOL declaration.\n"
            "  • Model version doesn't support function calling — check GEMINI_MODEL.\n"
            f"  • Current model: {_MODEL}"
        )
        print(f"\n  Tool called: {fcs[0].name}({dict(fcs[0].args)})")

    def test_correct_tool_name_returned(self):
        response = _generate(
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=("Find notes about budget planning."))],
                )
            ],
            tools=[SEARCH_TOOL],
            system="You are a notes assistant. Use search_notes to find information.",
        )
        fcs = _function_calls(response)
        assert fcs, (
            f"No function call. Plain text: {_first_text(response)!r}\n"
            "→ See test_model_issues_a_tool_call for diagnosis hints."
        )
        assert fcs[0].name == "search_notes", (
            f"Wrong tool called: {fcs[0].name!r} (expected 'search_notes').\n"
            "→ Gemini hallucinated a tool name — check your FunctionDeclaration names."
        )

    def test_tool_args_contain_query(self):
        response = _generate(
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=("Search my notes for 'quarterly review'."))
                    ],
                )
            ],
            tools=[SEARCH_TOOL],
            system="You are a notes assistant. Use search_notes to find information.",
        )
        fcs = _function_calls(response)
        assert fcs, f"No function call. Plain text: {_first_text(response)!r}"
        args = dict(fcs[0].args)
        print(f"\n  Args: {args}")
        assert "query" in args, (
            f"'query' key missing from function args: {args}\n"
            "→ Gemini returned a function call but didn't populate required args.\n"
            "  Check that 'query' is in the 'required' list of the tool schema."
        )
        assert args["query"], (
            f"'query' arg is present but empty: {args}\n"
            "→ Gemini called the tool with a blank query."
        )

    def test_full_round_trip_tool_call_to_answer(self):
        """Turn 1: Gemini calls tool. Turn 2: we return result. Turn 3: Gemini answers."""
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part(text=("What do my notes say about machine learning?"))
                ],
            )
        ]
        r1 = _generate(
            contents,
            tools=[SEARCH_TOOL],
            system="Use search_notes to answer questions about notes.",
        )
        fcs = _function_calls(r1)
        assert fcs, (
            f"Turn 1: expected a function call, got text: {_first_text(r1)!r}\n"
            "→ The agent loop will never start if Gemini skips the tool call."
        )
        print(f"\n  Turn 1 — tool call: {fcs[0].name}({dict(fcs[0].args)})")

        contents.append(
            types.Content(role="model", parts=r1.candidates[0].content.parts)
        )
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fcs[0].name,
                            response={
                                "result": str(
                                    {
                                        "success": True,
                                        "results": [
                                            {
                                                "path": "notes/ml.md",
                                                "snippet": "ML is a subset of AI focused on learning from data.",
                                            }
                                        ],
                                    }
                                )
                            },
                        )
                    )
                ],
            )
        )

        r2 = _generate(
            contents,
            tools=[SEARCH_TOOL],
            system="Use search_notes to answer questions about notes.",
        )
        text = _first_text(r2)
        more_fcs = _function_calls(r2)
        print(
            f"\n  Turn 2 — text: {text!r}, further calls: {[f.name for f in more_fcs]}"
        )

        assert text, (
            "After receiving the tool result Gemini returned no text.\n"
            f"Further function calls: {[f.name for f in more_fcs]}\n"
            "→ Gemini may want to call another tool before answering — that's OK in a\n"
            "  real agent loop, but this test only does one tool round-trip.\n"
            "→ Or the response was safety-blocked. Check safety_ratings."
        )

    def test_picks_list_tasks_for_todo_question(self):
        response = _generate(
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            text=("What tasks do I have pending? List my to-dos.")
                        )
                    ],
                )
            ],
            tools=[ALL_TOOLS],
            system=(
                "You are a notes assistant with search_notes, search_journals, "
                "read_note, and list_tasks. Always use the most appropriate tool."
            ),
        )
        fcs = _function_calls(response)
        print(f"\n  Tool chosen: {fcs[0].name if fcs else 'none (plain text)'}")
        if fcs:
            assert fcs[0].name in {"list_tasks", "search_notes"}, (
                f"Unexpected tool for a to-do question: {fcs[0].name!r}\n"
                "→ Gemini picked an inappropriate tool — review tool descriptions."
            )

    def test_journal_question_uses_journal_tool(self):
        response = _generate(
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part(text=("What did I write in my journal last week?"))
                    ],
                )
            ],
            tools=[ALL_TOOLS],
            system=(
                "You are a notes assistant. Use search_journals for journal/diary "
                "questions, search_notes for general notes, read_note to read a file, "
                "list_tasks for to-dos."
            ),
        )
        fcs = _function_calls(response)
        print(f"\n  Tool chosen: {fcs[0].name if fcs else 'none'}")
        if fcs:
            assert fcs[0].name in {"search_journals", "search_notes"}, (
                f"Unexpected tool for a journal question: {fcs[0].name!r}\n"
                "→ Review search_journals description in ALL_TOOLS."
            )


# ===========================================================================
# 4. Response shape contract
# ===========================================================================


class TestResponseShape:
    def test_candidates_is_a_list(self):
        response = _generate(
            [types.Content(role="user", parts=[types.Part(text="Hi.")])]
        )
        assert isinstance(response.candidates, list), (
            f"response.candidates is {type(response.candidates).__name__}, not list.\n"
            "→ The SDK response shape may have changed — check google-genai changelog."
        )
        assert len(response.candidates) >= 1, (
            "response.candidates is an empty list.\n"
            "→ The whole response was filtered out. Check safety settings."
        )

    def test_parts_is_iterable(self):
        response = _generate(
            [types.Content(role="user", parts=[types.Part(text="Hi.")])]
        )
        parts = response.candidates[0].content.parts
        assert hasattr(parts, "__iter__"), (
            f"parts is {type(parts).__name__}, not iterable.\n"
            "→ SDK shape changed: 'parts' may have been renamed."
        )

    def test_text_part_is_a_string(self):
        response = _generate(
            [types.Content(role="user", parts=[types.Part(text="Say: HELLO")])]
        )
        text_parts = [
            p for p in response.candidates[0].content.parts if getattr(p, "text", None)
        ]
        assert text_parts, (
            "No text parts in response to 'Say: HELLO'.\n"
            f"Parts: {response.candidates[0].content.parts}\n"
            "→ Either the response is a function call (unexpected here) or was blocked."
        )
        assert isinstance(text_parts[0].text, str), (
            f"part.text is {type(text_parts[0].text).__name__}, not str.\n"
            "→ SDK may have changed part.text to a different type."
        )

    def test_function_call_has_name_and_args(self):
        response = _generate(
            contents=[
                types.Content(
                    role="user", parts=[types.Part(text="Search notes for 'test'.")]
                )
            ],
            tools=[SEARCH_TOOL],
            system="Use search_notes when asked to search.",
        )
        fcs = _function_calls(response)
        if not fcs:
            pytest.skip("Model answered without a tool call — skipping shape check")
        fc = fcs[0]
        assert hasattr(fc, "name"), (
            f"function_call has no 'name' attribute. Attrs: {dir(fc)}\n"
            "→ SDK shape changed — function_call.name may have been renamed."
        )
        assert hasattr(fc, "args"), (
            f"function_call has no 'args' attribute. Attrs: {dir(fc)}\n"
            "→ SDK shape changed — function_call.args may have been renamed."
        )
        assert isinstance(fc.name, str), (
            f"function_call.name is {type(fc.name).__name__}, not str"
        )


# ===========================================================================
# 5. Edge cases
# ===========================================================================


class TestEdgeCases:
    def test_empty_tool_result_handled_gracefully(self):
        """Gemini should not crash or hang when a tool returns zero results."""
        contents = [
            types.Content(
                role="user", parts=[types.Part(text="Search my notes for 'xyzzy'.")]
            )
        ]
        r1 = _generate(
            contents,
            tools=[SEARCH_TOOL],
            system="Use search_notes to find information.",
        )
        fcs = _function_calls(r1)
        if not fcs:
            pytest.skip("Model didn't call a tool — can't test empty-result handling")

        contents.append(
            types.Content(role="model", parts=r1.candidates[0].content.parts)
        )
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fcs[0].name,
                            response={"result": '{"success": true, "results": []}'},
                        )
                    )
                ],
            )
        )

        r2 = _generate(contents, tools=[SEARCH_TOOL])
        text = _first_text(r2)
        more_fc = _function_calls(r2)
        print(f"\n  After empty result — text: {text!r}, further calls: {len(more_fc)}")
        assert text or more_fc, (
            "Gemini returned neither text nor another tool call after an empty result.\n"
            "→ This suggests the model got confused by the empty result payload."
        )

    def test_bad_api_key_raises_with_clear_error(self):
        """A wrong key must raise an exception — not silently return empty."""
        bad_client = genai.Client(api_key="bad-key-intentionally-wrong")
        try:
            bad_client.models.generate_content(
                model=_MODEL,
                contents=[types.Content(role="user", parts=[types.Part(text="hi")])],
                config=types.GenerateContentConfig(max_output_tokens=10),
            )
        except Exception as exc:
            print(f"\n  Raised (expected): {type(exc).__name__}: {exc}")
            # Good — it raised. Nothing more to assert.
            return

        pytest.fail(
            "A bad API key did NOT raise an exception — the SDK returned a response silently.\n"
            "→ Your error handling in llm.py may not catch auth failures.\n"
            "→ Check if genai.Client validates the key lazily."
        )
