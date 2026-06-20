"""Tests for the pure RAG helpers (chunking + cosine ranking).

The embedding model itself (sentence-transformers / torch) is not exercised here;
those are the heavy optional deps. We test the deterministic logic around it.
"""

import pytest

from umami_mcp import rag


def test_chunk_text_empty():
    assert rag.chunk_text("") == []
    assert rag.chunk_text("   \n  ") == []


def test_chunk_text_short_returns_single_chunk():
    assert rag.chunk_text("hello world") == ["hello world"]


def test_chunk_text_splits_long_text_within_bounds():
    text = "\n".join(f"line {i} " * 5 for i in range(400))
    chunks = rag.chunk_text(text, chunk_size=500, overlap=50)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)  # no empty chunks
    assert all(len(chunk) <= 500 for chunk in chunks)


def test_chunk_text_covers_all_content():
    text = "AAAA\nBBBB\nCCCC\nDDDD\nEEEE\nFFFF"
    chunks = rag.chunk_text(text, chunk_size=10, overlap=2)
    joined = "".join(chunks)
    for token in ("AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF"):
        assert token in joined


def test_rag_available_is_boolean_and_hint_is_actionable():
    assert isinstance(rag.rag_available(), bool)
    assert "rag" in rag.INSTALL_HINT


def test_top_k_indices_ranks_by_cosine_similarity():
    np = pytest.importorskip("numpy")
    matrix = np.array([[1.0, 0.0], [0.0, 1.0], [0.9, 0.1]])
    query = np.array([1.0, 0.0])
    # Row 0 is identical to the query; row 2 is close; row 1 is orthogonal.
    assert rag._top_k_indices(query, matrix, k=2) == [0, 2]


def test_top_k_indices_empty_matrix():
    np = pytest.importorskip("numpy")
    assert rag._top_k_indices(np.array([1.0, 0.0]), np.empty((0, 2)), k=3) == []
