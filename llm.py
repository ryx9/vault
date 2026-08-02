"""Optional LLM layer used only by `ask`. Everything works without it.

Retrieval always happens first; only the retrieved chunks are sent to the
model, never the whole vault. Uses a plain HTTP call to OpenRouter's
OpenAI-compatible endpoint rather than pulling in LangChain, to keep the
dependency footprint small -- swap in langchain.chat_models here if desired.
"""

from __future__ import annotations

import requests

import config
import retriever

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def is_configured() -> bool:
    return bool(config.OPENROUTER_API_KEY)


def _build_prompt(question: str, chunks: list[retriever.Result]) -> str:
    if chunks:
        context_blocks = []
        for i, c in enumerate(chunks, start=1):
            label = f"[{i}] {c.path}" + (f" — {c.heading}" if c.heading else "")
            context_blocks.append(f"{label}\n{c.text}")
        context = "\n\n".join(context_blocks)
        return (
            "Answer the question using the notes below when they are relevant. Cite "
            "sources only when you reference them. If the notes are not relevant, "
            "answer helpfully without inventing citations.\n\n"
            f"NOTES:\n{context}\n\nQUESTION: {question}"
        )
    return (
        "Answer the question helpfully. Use the notes below when they are relevant, "
        "but if there are no relevant notes, respond naturally and conversationally.\n\n"
        f"QUESTION: {question}"
    )


def ask(question: str, top_k: int = 6, history: list[dict] | None = None) -> dict:
    """Runs hybrid retrieval, then (optionally) asks the LLM.

    Returns {"answer": str | None, "chunks": [Result]} — answer is None if
    no LLM is configured, in which case the caller should show raw chunks.
    """
    chunks = retriever.hybrid_search(question, top_k=top_k)

    if not is_configured():
        return {"answer": None, "chunks": chunks}

    prompt = _build_prompt(question, chunks)
    messages = [
        {
            "role": "system",
            "content": (
                "You are a helpful personal notes assistant. Use the notes below when "
                "they are relevant, and cite sources only when you quote or refer to them. "
                "If the notes are not relevant, answer helpfully without inventing citations."
            ),
        }
    ]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            OPENROUTER_URL,
            headers={"Authorization": f"Bearer {config.OPENROUTER_API_KEY}"},
            json={
                "model": config.OPENROUTER_MODEL,
                "messages": messages,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        answer = data["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError) as exc:
        answer = f"(LLM request failed: {exc}. Showing retrieved notes instead.)"

    return {"answer": answer, "chunks": chunks}
