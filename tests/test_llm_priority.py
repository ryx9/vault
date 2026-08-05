from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import llm


def test_ask_prefers_gemini_then_falls_back_to_openrouter(monkeypatch):
    monkeypatch.setattr(llm.config, "GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(llm.config, "OPENROUTER_API_KEY", "openrouter-key")

    calls: list[str] = []

    def fake_hybrid_search(question, top_k=6):
        return []

    def fake_gemini(question, chunks, history):
        calls.append("gemini")
        raise RuntimeError("gemini failed")

    def fake_openrouter(question, chunks, history):
        calls.append("openrouter")
        return "fallback answer"

    monkeypatch.setattr(llm.retriever, "hybrid_search", fake_hybrid_search)
    monkeypatch.setattr(llm, "_run_gemini_agent", fake_gemini)
    monkeypatch.setattr(llm, "_run_openrouter", fake_openrouter)

    result = llm.ask("hello")

    assert result["answer"] == "fallback answer"
    assert calls == ["gemini", "openrouter"]
