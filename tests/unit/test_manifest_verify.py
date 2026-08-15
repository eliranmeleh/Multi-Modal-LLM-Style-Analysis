"""The failure branches of ``corpus verify``.

The happy path is covered by ``tests/data/test_corpus_integrity.py`` against the real corpus. What
matters here is the opposite: that each way a corpus can go wrong actually trips the check. A
verifier that cannot fail is decoration.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mmlsa.corpus.loader import load_sources, write_text
from mmlsa.corpus.manifest import build_manifest, read_manifest, verify, write_manifest
from mmlsa.corpus.normalize import NormalizationReport
from tests.conftest import REPO_ROOT

FUNCTION_WORDS = "data/function_words/en_core_v1.txt"

BODY = "ACT I\n" + " ".join(f"word{i}" for i in range(600)) + "\n"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A miniature project root with a sources file and one fetched text."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "function_words").mkdir()
    real_list = (REPO_ROOT / FUNCTION_WORDS).read_text(encoding="utf-8")
    (tmp_path / FUNCTION_WORDS).write_text(real_list, encoding="utf-8")

    (tmp_path / "data" / "corpus_sources.yaml").write_text(
        yaml.safe_dump(
            {
                "author_label": "Author",
                "texts": [
                    {"id": "text_a", "title": "A", "gutenberg_id": 1, "expected_words": 600},
                    {"id": "text_b", "title": "B", "gutenberg_id": 2, "expected_words": 600},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def _build(workspace: Path, texts: dict[str, str]) -> dict:
    """Write the texts and generate a manifest for them."""
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")
    for source in sources.sets["texts"]:
        write_text(source, workspace, texts[source.id])

    manifest = build_manifest(
        sources,
        workspace,
        texts,
        {k: NormalizationReport() for k in texts},
        function_words_path=FUNCTION_WORDS,
    )
    write_manifest(manifest, workspace / "data" / "manifest.json")
    return manifest


def test_a_consistent_corpus_passes(workspace: Path) -> None:
    """The control: without this, every assertion below could pass for the wrong reason."""
    texts = {"text_a": BODY, "text_b": BODY}
    manifest = _build(workspace, texts)
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    result = verify(sources, workspace, manifest, expected_count=2)

    assert result.ok, result.failures
    assert result.checks_run >= 2


def test_an_edited_text_is_caught_by_its_checksum(workspace: Path) -> None:
    """The single most valuable check: a file changed after the manifest was written."""
    texts = {"text_a": BODY, "text_b": BODY}
    manifest = _build(workspace, texts)
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    path = workspace / "data" / "corpus" / "text_a.txt"
    path.write_text(BODY + "an extra line slipped in\n", encoding="utf-8")

    result = verify(sources, workspace, manifest, expected_count=2)

    assert not result.ok
    assert any("checksum drift" in f for f in result.failures)


def test_a_deleted_text_is_caught(workspace: Path) -> None:
    """A missing creation would otherwise silently shrink the corpus."""
    texts = {"text_a": BODY, "text_b": BODY}
    manifest = _build(workspace, texts)
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    (workspace / "data" / "corpus" / "text_b.txt").unlink()

    result = verify(sources, workspace, manifest, expected_count=2)

    assert not result.ok
    assert any("missing" in f for f in result.failures)


def test_surviving_gutenberg_boilerplate_is_caught(workspace: Path) -> None:
    """Legal English left in a creation would add hundreds of function words to it."""
    contaminated = BODY + "\nEnd of the Project Gutenberg EBook of Something\n"
    texts = {"text_a": contaminated, "text_b": BODY}
    manifest = _build(workspace, texts)
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    result = verify(sources, workspace, manifest, expected_count=2)

    assert not result.ok
    assert any("boilerplate" in f for f in result.failures)


def test_a_wrong_corpus_size_is_caught(workspace: Path) -> None:
    """The count the specification names is checked, not assumed."""
    texts = {"text_a": BODY, "text_b": BODY}
    manifest = _build(workspace, texts)
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    result = verify(sources, workspace, manifest, expected_count=49)

    assert not result.ok
    assert any("expected 49" in f for f in result.failures)


def test_a_word_count_outside_its_band_warns_but_does_not_fail(workspace: Path) -> None:
    """A rough estimate being rough is not a reason to refuse to run."""
    texts = {"text_a": "ACT I\n" + " ".join(f"w{i}" for i in range(50)), "text_b": BODY}
    manifest = _build(workspace, texts)
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    result = verify(sources, workspace, manifest, expected_count=2)

    assert result.ok
    assert any("expected about" in w for w in result.warnings)


def test_an_empty_text_fails_rather_than_warning(workspace: Path) -> None:
    """Zero words is not a rough estimate; it is a broken creation."""
    texts = {"text_a": "\n", "text_b": BODY}
    manifest = _build(workspace, texts)
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    result = verify(sources, workspace, manifest, expected_count=2)

    assert not result.ok
    assert any("empty" in f for f in result.failures)


def test_a_text_no_longer_declared_is_caught(workspace: Path) -> None:
    """A creation removed from the sources file but left in the manifest is a stale corpus."""
    texts = {"text_a": BODY, "text_b": BODY}
    manifest = _build(workspace, texts)

    (workspace / "data" / "corpus_sources.yaml").write_text(
        yaml.safe_dump(
            {
                "author_label": "Author",
                "texts": [{"id": "text_a", "title": "A", "gutenberg_id": 1}],
            }
        ),
        encoding="utf-8",
    )
    sources = load_sources(workspace / "data" / "corpus_sources.yaml")

    result = verify(sources, workspace, manifest, expected_count=1)

    assert not result.ok
    assert any("no longer declared" in f for f in result.failures)


def test_reading_a_missing_manifest_says_what_to_run(workspace: Path) -> None:
    """The error is the next command, not just a stack trace."""
    from mmlsa.corpus.loader import CorpusError

    with pytest.raises(CorpusError, match="corpus fetch"):
        read_manifest(workspace / "data" / "nothing.json")


def test_the_manifest_records_totals_and_provenance(workspace: Path) -> None:
    """What the report and any future reader depend on."""
    manifest = _build(workspace, {"text_a": BODY, "text_b": BODY})

    assert manifest["totals"]["n_texts"] == 2
    assert manifest["totals"]["n_words"] == 2 * len(BODY.split())
    assert manifest["function_words"]["count"] == 127
    assert all(e["source_urls"] for e in manifest["sets"]["texts"])
