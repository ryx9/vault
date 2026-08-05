"""Embeddings and vector storage.

The vector database (ChromaDB) is a cache, not source of truth: it stores
only embeddings + chunk metadata (path, heading, text). Everything here can
be regenerated from the markdown files at any time via reindex.
"""

from __future__ import annotations

import hashlib
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import chromadb

import config
import parser

_model = None
_client = None
_collection = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(config.EMBEDDING_MODEL)
    return _model


def preload_model() -> None:
    """Load the embedding model and Chroma collection quietly on startup."""
    global _model, _collection
    if _model is not None and _collection is not None:
        return

    try:
        from transformers.utils import logging as transformers_logging

        transformers_logging.set_verbosity_error()
    except ImportError:
        pass

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        get_model()
        get_collection()


def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        _collection = _client.get_or_create_collection(config.CHROMA_COLLECTION)
    return _collection


def _chunk_id(chunk: parser.Chunk, index: int) -> str:
    digest = hashlib.sha1(f"{chunk.path}::{index}".encode()).hexdigest()[:16]
    return digest


def remove_file_embeddings(rel_path: str) -> None:
    collection = get_collection()
    try:
        collection.delete(where={"path": rel_path})
    except Exception:
        pass


def reindex_file(path: Path) -> int:
    """Regenerate embeddings for a single file. Returns chunk count."""
    rel = parser.relative_path(path)
    remove_file_embeddings(rel)

    chunks = parser.chunk_markdown(path)
    if not chunks:
        return 0

    model = get_model()
    texts = [f"{c.heading}\n{c.text}" if c.heading else c.text for c in chunks]
    vectors = model.encode(texts, normalize_embeddings=True).tolist()

    ids = [_chunk_id(c, i) for i, c in enumerate(chunks)]
    metadatas = [{"path": c.path, "heading": c.heading} for c in chunks]
    documents = [c.text for c in chunks]

    get_collection().add(ids=ids, embeddings=vectors, metadatas=metadatas, documents=documents)
    return len(chunks)


def reindex_all(notes_dir: Path = config.NOTES_DIR) -> int:
    total = 0
    for md_file in parser.iter_markdown_files(notes_dir):
        total += reindex_file(md_file)
    return total


def semantic_search(query: str, top_k: int = 8) -> list[dict]:
    collection = get_collection()
    if collection.count() == 0:
        return []

    model = get_model()
    vector = model.encode([query], normalize_embeddings=True).tolist()

    results = collection.query(query_embeddings=vector, n_results=min(top_k, collection.count()))
    out = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for i in range(len(ids)):
        similarity = 1 - dists[i]  # cosine distance -> similarity
        out.append(
            {
                "path": metas[i].get("path", ""),
                "heading": metas[i].get("heading", ""),
                "text": docs[i],
                "score": similarity,
            }
        )
    return out


def chunk_count() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0
