"""Corpus acquisition, normalization and integrity checking."""

from mmlsa.corpus.loader import (
    CorpusError,
    CorpusSources,
    TextSource,
    load_corpus,
    load_sources,
    load_text,
)
from mmlsa.corpus.normalize import count_words, normalize

__all__ = [
    "CorpusError",
    "CorpusSources",
    "TextSource",
    "count_words",
    "load_corpus",
    "load_sources",
    "load_text",
    "normalize",
]
