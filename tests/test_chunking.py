"""Chunking regressions."""

import pytest

from app.services.rag import chunk_text


def test_basic_chunking() -> None:
    text = "a" * 250
    chunks = chunk_text(text, chunk_size=100, chunk_overlap=20)
    assert chunks
    assert all(len(c) <= 100 for c in chunks)
    assert "".join(chunks).replace(" ", "") != ""


@pytest.mark.parametrize(
    "text",
    [
        # The original failure mode: many short lines meant the boundary search
        # landed within chunk_overlap of `start`, so `start = end - overlap`
        # moved backwards and the loop never terminated.
        "\n".join("x" for _ in range(500)),
        "\n\n".join("word" for _ in range(300)),
        ". ".join("s" for _ in range(400)),
        "\n" * 1000,
        " " * 1000,
        "a\n\nb\n\nc\n\n" * 200,
        "短い行\n" * 300,
    ],
    ids=["short-lines", "short-paras", "short-sents", "newlines", "spaces",
         "mixed", "unicode"],
)
def test_chunk_text_always_terminates(text: str) -> None:
    """Must finish, and must not emit near-duplicate floods.

    The bound is tight on purpose. An earlier version of this test allowed
    10_000 chunks, which let a real bug through: a 286-char document produced
    201 chunks because the loop rewound by `overlap` after consuming the whole
    text and then crawled forward one character at a time.
    """
    size, overlap = 100, 80
    chunks = chunk_text(text, chunk_size=size, chunk_overlap=overlap)
    if not chunks:
        return  # whitespace-only input legitimately yields nothing

    # Each iteration should advance by roughly (size - overlap). Boundary
    # backoff can shorten that, so allow down to half the nominal stride —
    # still far above the ~1 char/chunk of a rewinding loop.
    stride = size - overlap
    min_advance = stride // 2
    advance = len(text) / len(chunks)
    assert advance >= min_advance, (
        f"{len(chunks)} chunks for {len(text)} chars "
        f"(advance {advance:.1f} < {min_advance}) — loop is rewinding"
    )


@pytest.mark.parametrize("length", [1, 50, 286, 999, 1000, 1001])
def test_short_documents_are_not_over_chunked(length: int) -> None:
    """A document shorter than chunk_size must yield exactly one chunk."""
    text = "word " * (length // 5) or "x"
    chunks = chunk_text(text, chunk_size=1000, chunk_overlap=200)
    if len(text) <= 1000:
        assert len(chunks) == 1, f"{len(text)} chars produced {len(chunks)} chunks"
    else:
        assert len(chunks) <= 3


def test_no_duplicate_chunks_on_typical_text() -> None:
    text = ". ".join(f"Sentence number {i} about satellites" for i in range(60))
    chunks = chunk_text(text, chunk_size=200, chunk_overlap=40)
    assert len(chunks) == len(set(chunks)), "emitted duplicate chunks"


def test_overlap_larger_than_size_is_clamped() -> None:
    chunks = chunk_text("abc " * 200, chunk_size=50, chunk_overlap=999)
    assert len(chunks) < 1000


def test_empty_input() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_invalid_chunk_size() -> None:
    with pytest.raises(ValueError):
        chunk_text("hello", chunk_size=0)


def test_settings_read_at_call_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """They used to be default-argument values, frozen at import."""
    from app.core import config

    monkeypatch.setattr(config.settings, "CHUNK_SIZE", 40)
    monkeypatch.setattr(config.settings, "CHUNK_OVERLAP", 5)
    chunks = chunk_text("z" * 200)
    assert all(len(c) <= 40 for c in chunks)
