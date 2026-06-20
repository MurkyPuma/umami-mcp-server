"""Optional semantic search over user journeys (the ``get_docs`` tool).

Retrieves the chunks of session-activity data most relevant to a question, so the
model can analyze specific behaviors without every raw journey being stuffed into
the context window.

Two deliberate changes from the original:

* **No global vector store.** The original kept a module-level FAISS index and
  *added* to it on every call without ever clearing it, so a second ``get_docs``
  call retrieved chunks left over from earlier, unrelated queries. Here each call
  embeds and ranks its own documents and keeps nothing, so results can't leak
  between calls.
* **Lighter stack.** Dropped langchain + faiss + scikit-learn in favor of
  ``sentence-transformers`` for embeddings and a few lines of NumPy for cosine
  ranking. Same capability, far fewer moving parts and no deprecated APIs.

The embedding model is heavy (torch), so it lives behind the ``rag`` extra and is
imported lazily. The chunking and ranking helpers below are pure and unit-tested.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    import numpy as np

_MODEL_NAME = "all-MiniLM-L6-v2"
_model = None  # cached SentenceTransformer (the model is fine to reuse; the index is not)

INSTALL_HINT = (
    "Semantic journey search needs the optional 'rag' extra. Install it with:\n"
    "    pip install 'umami-mcp-server[rag]'"
)


def rag_available() -> bool:
    """True if the optional RAG deps can be imported (without importing torch)."""
    return (
        importlib.util.find_spec("sentence_transformers") is not None
        and importlib.util.find_spec("numpy") is not None
    )


def chunk_text(text: str, *, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split ``text`` into ~``chunk_size``-character chunks, preferring line breaks.

    Pure and dependency-free so it can be tested without the embedding model.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size - 1))

    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        window = text[start:end]
        if end < len(text):
            # Prefer to break on the last newline in the window for cleaner chunks.
            newline = window.rfind("\n")
            if newline > overlap:
                end = start + newline
                window = text[start:end]
        chunks.append(window.strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)

    return [c for c in chunks if c]


def _top_k_indices(query_vec: np.ndarray, matrix: np.ndarray, k: int) -> list[int]:
    """Indices of the ``k`` rows of ``matrix`` most cosine-similar to ``query_vec``."""
    import numpy as np

    if matrix.shape[0] == 0:
        return []
    matrix_norm = matrix / (np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-12)
    query_norm = query_vec / (np.linalg.norm(query_vec) + 1e-12)
    scores = matrix_norm @ query_norm
    k = min(k, scores.shape[0])
    # argsort descending, take top k.
    return np.argsort(-scores)[:k].tolist()


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def semantic_search(
    documents: list[str],
    question: str,
    *,
    k: int = 20,
    chunk_size: int = 1000,
) -> list[str]:
    """Return up to ``k`` chunks across ``documents`` most relevant to ``question``.

    Each call is self-contained: it chunks and embeds the documents passed in and
    retains nothing afterward.

    Raises:
        RuntimeError: If the optional RAG dependencies are not installed.
    """
    if not rag_available():
        raise RuntimeError(INSTALL_HINT)

    import numpy as np

    chunks: list[str] = []
    for document in documents:
        chunks.extend(chunk_text(document, chunk_size=chunk_size))
    if not chunks:
        return []

    model = _get_model()
    chunk_vecs = np.asarray(model.encode(chunks))
    query_vec = np.asarray(model.encode([question])[0])

    indices = _top_k_indices(query_vec, chunk_vecs, k)
    return [chunks[i] for i in indices]
