"""The corpus on disk, checked against the manifest and against the specification's expectations.

These are the tests that would catch a text edited by accident, a re-download that changed edition,
or a normalization rule that quietly stopped firing. None of those would crash anything; they would
just move the numbers.
"""

from __future__ import annotations

import pytest

from mmlsa.chunking import chunk_text, split_words
from mmlsa.corpus.gutenberg import has_residual_marker
from mmlsa.corpus.loader import load_sources, load_text, text_path
from mmlsa.corpus.manifest import read_manifest, verify
from mmlsa.distance.fwed import FunctionWordEditDistance
from tests.conftest import REPO_ROOT

SOURCES_PATH = REPO_ROOT / "data" / "corpus_sources.yaml"
MANIFEST_PATH = REPO_ROOT / "data" / "manifest.json"
FUNCTION_WORDS = str(REPO_ROOT / "data" / "function_words" / "en_core_v1.txt")

pytestmark = pytest.mark.skipif(
    not MANIFEST_PATH.is_file(),
    reason="corpus not fetched; run 'python -m mmlsa corpus fetch'",
)


@pytest.fixture(scope="module")
def sources():
    """The declared corpus."""
    return load_sources(SOURCES_PATH)


@pytest.fixture(scope="module")
def manifest():
    """The generated manifest."""
    return read_manifest(MANIFEST_PATH)


@pytest.fixture(scope="module")
def corpus_texts(sources):
    """The 49 normalized creations, keyed by id."""
    return {s.id: load_text(s, REPO_ROOT) for s in sources.sets["texts"]}


# ------------------------------------------------------------------------------- the whole check


def test_corpus_verify_passes(sources, manifest) -> None:
    """The milestone M2 acceptance criterion, as one assertion."""
    result = verify(sources, REPO_ROOT, manifest, expected_count=49)

    assert result.ok, "verification failures:\n" + "\n".join(result.failures)
    assert result.checks_run > 49


# ------------------------------------------------------------------------------------- the corpus


def test_the_corpus_holds_exactly_forty_nine_creations(manifest) -> None:
    """The count the specification and the reference paper both name."""
    assert manifest["totals"]["n_texts"] == 49
    assert len(manifest["sets"]["texts"]) == 49


def test_the_corpus_total_is_in_the_expected_range(manifest) -> None:
    """The stored corpus, including the apparatus we deliberately keep.

    ``docs/DATA.md`` section 7 estimates 0.9 to 1.0 million words. That figure is spoken text: the
    stored corpus also keeps speaker prefixes and stage directions, which together are 10.2 percent
    of it. See ``docs/RESULTS.md`` F-00 for the measurement.
    """
    from mmlsa.corpus.manifest import CORPUS_WORD_RANGE

    total = manifest["totals"]["n_words"]
    low, high = CORPUS_WORD_RANGE

    assert low <= total <= high, f"corpus totals {total:,} words, expected {low:,} to {high:,}"


def test_every_creation_has_content(corpus_texts) -> None:
    """A text that normalized to nothing would score nothing and be invisible in the output."""
    empty = [text_id for text_id, text in corpus_texts.items() if len(split_words(text)) < 500]

    assert not empty, f"suspiciously short creations: {empty}"


def test_no_gutenberg_boilerplate_survives(corpus_texts) -> None:
    """A surviving licence header would add hundreds of function words to a creation."""
    offenders = [text_id for text_id, text in corpus_texts.items() if has_residual_marker(text)]

    assert not offenders, f"Project Gutenberg boilerplate found in: {offenders}"


def test_every_creation_is_stored_where_the_manifest_says(sources) -> None:
    """The path convention the rest of the pipeline relies on."""
    for source in sources.sets["texts"]:
        assert text_path(REPO_ROOT, source).is_file()


def test_creation_ids_are_filesystem_safe(sources) -> None:
    """Ids become filenames and artifact keys, so they must survive both."""
    for source in sources.all_texts():
        assert source.id.replace("_", "").isalnum(), f"unsafe id: {source.id}"
        assert source.id == source.id.lower()


# --------------------------------------------------------------------- properties over real text


@pytest.mark.parametrize("chunk_size", [200, 400, 600])
def test_chunking_covers_every_creation_completely(corpus_texts, chunk_size: int) -> None:
    """The full-coverage property of milestone M3, over the real corpus rather than fixtures.

    This is the check M3 could not make until the corpus existed.
    """
    for text_id, text in corpus_texts.items():
        chunks = chunk_text(text, chunk_size, creation_id=text_id)
        rejoined = [word for chunk in chunks for word in split_words(chunk.text)]

        assert rejoined == split_words(text), f"chunking lost or reordered words in {text_id}"


def test_chunk_sizes_are_uniform_except_the_tail(corpus_texts) -> None:
    """Every chunk is P words except possibly the last, on real text."""
    for text_id, text in corpus_texts.items():
        chunks = chunk_text(text, 400, creation_id=text_id)

        assert all(c.n_words == 400 for c in chunks[:-1]), text_id
        assert 1 <= chunks[-1].n_words <= 400, text_id


def test_distance_of_every_real_chunk_against_itself_is_zero(corpus_texts) -> None:
    """``delta(x, x) == 0`` over every chunk in the corpus, not just over a toy string.

    The other property milestone M3 deferred until there was a corpus to run it on.
    """
    delta = FunctionWordEditDistance(FUNCTION_WORDS)

    for text_id, text in corpus_texts.items():
        for chunk in chunk_text(text, 400, creation_id=text_id):
            result = delta(chunk.text, chunk.text)
            assert result.value == 0.0, f"{text_id} chunk {chunk.index}"


def test_real_chunks_contain_function_words(corpus_texts) -> None:
    """A corpus whose chunks were mostly degenerate would silently measure nothing.

    A 400-word passage of English with no function words at all is essentially impossible, so a
    non-trivial degenerate rate here would mean the tokenizer or the word list is broken.
    """
    delta = FunctionWordEditDistance(FUNCTION_WORDS)
    total = degenerate = 0

    for text_id, text in corpus_texts.items():
        for chunk in chunk_text(text, 400, creation_id=text_id):
            total += 1
            if delta(chunk.text, chunk.text).degenerate:
                degenerate += 1

    assert total > 2_000, f"only {total} chunks; the corpus looks too small"
    assert degenerate == 0, f"{degenerate} of {total} chunks contain no function words"


def test_the_expected_chunk_count_matches_the_specification(corpus_texts) -> None:
    """docs/SPEC.md section 9: roughly 2,400 to 2,500 chunks at P = 400."""
    total = sum(len(chunk_text(t, 400, creation_id=i)) for i, t in corpus_texts.items())

    assert 2_300 <= total <= 2_700, f"{total} chunks at P=400"


# ------------------------------------------------------------------------------------- manifest


def test_manifest_records_the_normalization_choices(manifest) -> None:
    """docs/DATA.md requires the speaker-prefix decision to be stated, not implied."""
    assert manifest["speaker_prefixes"] == "kept"
    assert manifest["stage_directions"] == "kept"
    assert manifest["normalization_version"] >= 1


def test_manifest_records_the_function_word_list_it_was_built_against(manifest) -> None:
    """Changing the list invalidates every delta, so its identity belongs in the corpus record."""
    entry = manifest["function_words"]

    assert entry["file"] == "en_core_v1.txt"
    assert 110 <= entry["count"] <= 130
    assert len(entry["sha256"]) == 64


def test_every_manifest_entry_carries_provenance(manifest) -> None:
    """Each text must say where it came from, for the corpus to be reproducible by anyone else."""
    for name, entries in manifest["sets"].items():
        for entry in entries:
            assert entry["source_urls"], f"{name}/{entry['id']} has no source url"
            assert len(entry["sha256"]) == 64
            assert entry["n_words"] > 0
