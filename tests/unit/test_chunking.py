"""Step 2 — chunking.

The properties here are what make "full coverage, no sampling" checkable rather than asserted.
A chunker that loses a word does not crash; it quietly changes every score downstream.
"""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mmlsa.chunking import ChunkingError, chunk_text, expected_chunk_count, split_words

SAMPLE = " ".join(f"word{i}" for i in range(1000))


# -------------------------------------------------------------------------------- full coverage


@pytest.mark.parametrize("chunk_size", [1, 2, 7, 100, 400, 999, 1000, 1001, 5000])
def test_chunks_reproduce_the_source_word_sequence_exactly(chunk_size: int) -> None:
    """Round trip: no loss, no duplication, no reordering. This is the full-coverage guarantee."""
    chunks = chunk_text(SAMPLE, chunk_size, creation_id="sample")
    rejoined = [word for chunk in chunks for word in split_words(chunk.text)]

    assert rejoined == split_words(SAMPLE)


@given(
    words=st.lists(st.text(alphabet="abcdefg", min_size=1, max_size=6), min_size=1, max_size=300),
    chunk_size=st.integers(min_value=1, max_value=50),
)
def test_full_coverage_holds_for_arbitrary_texts(words: list[str], chunk_size: int) -> None:
    """The round-trip property, over generated inputs rather than one fixed sample."""
    text = " ".join(words)
    chunks = chunk_text(text, chunk_size)
    rejoined = [word for chunk in chunks for word in split_words(chunk.text)]

    assert rejoined == words


@pytest.mark.parametrize("chunk_size", [1, 7, 100, 400])
def test_word_ranges_tile_the_text_without_gaps_or_overlap(chunk_size: int) -> None:
    """Each chunk records the half-open word range it covers, and the ranges must tile exactly."""
    chunks = chunk_text(SAMPLE, chunk_size)

    assert chunks[0].word_start == 0
    assert chunks[-1].word_end == len(split_words(SAMPLE))
    for earlier, later in itertools.pairwise(chunks):
        assert earlier.word_end == later.word_start


# ---------------------------------------------------------------------------------- sizes, count


@pytest.mark.parametrize("chunk_size", [1, 3, 50, 400, 997])
def test_every_chunk_is_full_except_possibly_the_last(chunk_size: int) -> None:
    """The specification allows exactly one short chunk, at the end."""
    chunks = chunk_text(SAMPLE, chunk_size)

    for chunk in chunks[:-1]:
        assert chunk.n_words == chunk_size
    assert 1 <= chunks[-1].n_words <= chunk_size


@pytest.mark.parametrize(
    ("n_words", "chunk_size", "expected"),
    [(1000, 400, 3), (800, 400, 2), (400, 400, 1), (399, 400, 1), (401, 400, 2), (1, 1, 1)],
)
def test_chunk_count_is_the_ceiling_of_the_division(
    n_words: int, chunk_size: int, expected: int
) -> None:
    """``n_chunks == ceil(n_words / P)``, with the arithmetic pinned at the boundaries."""
    text = " ".join(f"w{i}" for i in range(n_words))

    assert len(chunk_text(text, chunk_size)) == expected
    assert expected_chunk_count(n_words, chunk_size) == expected


def test_trailing_short_chunk_is_kept_not_merged() -> None:
    """DECISIONS.md I6: merging the tail would change the specified quantity."""
    text = " ".join(f"w{i}" for i in range(410))
    chunks = chunk_text(text, 400)

    assert len(chunks) == 2
    assert chunks[1].n_words == 10


# ---------------------------------------------------------------------------- indices, determinism


def test_chunk_indices_are_consecutive_from_zero() -> None:
    """Indices identify a chunk in the artifacts, so they must be dense and ordered."""
    chunks = chunk_text(SAMPLE, 60, creation_id="sample")

    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.creation_id == "sample" for chunk in chunks)


def test_chunking_is_deterministic() -> None:
    """Same input, byte-identical chunks, including their content hashes."""
    first = chunk_text(SAMPLE, 400, creation_id="sample")
    second = chunk_text(SAMPLE, 400, creation_id="sample")

    assert [c.text for c in first] == [c.text for c in second]
    assert [c.sha256 for c in first] == [c.sha256 for c in second]


def test_whitespace_runs_collapse_to_single_separators() -> None:
    """A word is a maximal run of non-whitespace, so line breaks and runs of spaces are separators."""
    chunks = chunk_text("alpha   beta\n\ngamma\tdelta", 2)

    assert [chunk.text for chunk in chunks] == ["alpha beta", "gamma delta"]


# ------------------------------------------------------------------------------------ edge cases


def test_text_shorter_than_the_chunk_size_yields_one_chunk() -> None:
    """A short creation is one short chunk, not zero chunks and not an error."""
    chunks = chunk_text("only a handful of words", 400)

    assert len(chunks) == 1
    assert chunks[0].n_words == 5


@pytest.mark.parametrize("text", ["", "   ", "\n\n\t "])
def test_empty_text_raises_rather_than_yielding_nothing(text: str) -> None:
    """A creation with no words is a data error and must be loud, not an empty chunk list."""
    with pytest.raises(ChunkingError, match="no words"):
        chunk_text(text, 400, creation_id="empty_creation")


@pytest.mark.parametrize("chunk_size", [0, -1])
def test_non_positive_chunk_size_raises(chunk_size: int) -> None:
    """Guards against a misconfigured P silently producing nothing."""
    with pytest.raises(ChunkingError, match="at least 1 word"):
        chunk_text(SAMPLE, chunk_size)
