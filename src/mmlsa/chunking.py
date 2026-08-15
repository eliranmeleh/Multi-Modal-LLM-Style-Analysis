"""Step 2 — full-text chunking.

Each creation is partitioned into consecutive, non-overlapping chunks of ``P`` words with **full
coverage**: every word appears in exactly one chunk, in order. There is no sampling, and the last
chunk of a creation may be shorter than ``P``.

Full coverage is a specification decision, not an implementation convenience (``docs/DECISIONS.md``
S4): it removes sampling as a source of run-to-run variance and as a reviewer objection.

See ``docs/SPEC.md`` section 3, Step 2.
"""

from __future__ import annotations

from dataclasses import dataclass

from mmlsa.utils.hashing import hash_text


class ChunkingError(Exception):
    """Raised when a text cannot be chunked at all, rather than yielding zero chunks silently."""


@dataclass(frozen=True)
class Chunk:
    """One chunk of one creation, with the provenance needed to trace a score back to it (R7)."""

    creation_id: str
    index: int
    text: str
    n_words: int
    word_start: int
    word_end: int

    @property
    def sha256(self) -> str:
        """Content hash of the chunk text, recorded in the run artifacts."""
        return hash_text(self.text)


def split_words(text: str) -> list[str]:
    """Split normalized text into words.

    A word is a maximal run of non-whitespace characters, which is the definition used consistently
    for chunking, for length statistics and for the corpus manifest. See ``docs/DATA.md`` section 4.
    """
    return text.split()


def chunk_text(text: str, chunk_size: int, *, creation_id: str = "") -> list[Chunk]:
    """Partition ``text`` into consecutive chunks of ``chunk_size`` words.

    The chunk boundaries fall between words and never inside one. Chunk ``j`` covers word indices
    ``[j * P, min((j + 1) * P, L))``, so ``n_chunks == ceil(L / P)`` exactly.

    A trailing chunk shorter than ``chunk_size`` is kept as is and never merged into its predecessor
    (``docs/DECISIONS.md`` I6): merging would change the specified quantity. Its ``n_words`` is
    recorded so that a length-weighted aggregation can be reported as a sensitivity check.

    Raises ``ChunkingError`` for an empty text: a creation with no words is a data error, and
    returning an empty list would let it pass through the pipeline scoring nothing.
    """
    if chunk_size < 1:
        raise ChunkingError(f"chunk size must be at least 1 word, got {chunk_size}")

    words = split_words(text)
    if not words:
        label = creation_id or "<unnamed>"
        raise ChunkingError(f"creation '{label}' contains no words")

    chunks: list[Chunk] = []
    for index, start in enumerate(range(0, len(words), chunk_size)):
        end = min(start + chunk_size, len(words))
        piece = words[start:end]
        chunks.append(
            Chunk(
                creation_id=creation_id,
                index=index,
                text=" ".join(piece),
                n_words=len(piece),
                word_start=start,
                word_end=end,
            )
        )

    return chunks


def expected_chunk_count(n_words: int, chunk_size: int) -> int:
    """The number of chunks a text of ``n_words`` words yields: ``ceil(n_words / chunk_size)``."""
    if chunk_size < 1:
        raise ChunkingError(f"chunk size must be at least 1 word, got {chunk_size}")
    return -(-n_words // chunk_size)
