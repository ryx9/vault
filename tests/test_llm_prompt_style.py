from __future__ import annotations

import llm


def test_system_prompt_discourages_reasoning_exposition():
    prompt = llm._SYSTEM_PROMPT.lower()

    assert "do not reveal your reasoning" in prompt
    assert "do not narrate your process" in prompt
    assert "answer directly" in prompt
