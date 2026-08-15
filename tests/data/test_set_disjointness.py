"""The integrity rules that protect the validity of the experiments.

A text used both as injected noise and as a held-out test subject turns a validation test into a
self-fulfilling result. Nothing about the output would look wrong, which is precisely why this is a
test and not a convention.

See ``docs/DATA.md`` section 1.1.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mmlsa.corpus.loader import SET_NAMES, CorpusError, load_sources, text_path
from tests.conftest import REPO_ROOT

SOURCES_PATH = REPO_ROOT / "data" / "corpus_sources.yaml"


@pytest.fixture(scope="module")
def sources():
    """The declared corpus."""
    return load_sources(SOURCES_PATH)


def test_the_sources_file_exists_and_declares_every_set(sources) -> None:
    """A missing set would make the disjointness checks below pass vacuously."""
    for name in SET_NAMES:
        assert sources.sets.get(name), f"set '{name}' is empty or undeclared"


def test_no_text_id_appears_in_more_than_one_set(sources) -> None:
    """Rule 1, at the level of our own identifiers."""
    ids = [source.id for source in sources.all_texts()]
    duplicates = sorted({text_id for text_id in ids if ids.count(text_id) > 1})

    assert not duplicates, f"ids declared in more than one place: {duplicates}"


def test_no_gutenberg_text_appears_in_more_than_one_set(sources) -> None:
    """Rule 1, at the level of the underlying source. This is the one that actually matters."""
    seen: dict[int, str] = {}
    collisions: list[str] = []

    for source in sources.all_texts():
        for gutenberg_id in source.gutenberg_ids:
            if gutenberg_id in seen:
                collisions.append(
                    f"{gutenberg_id} in both '{seen[gutenberg_id]}' and '{source.set_name}'"
                )
            seen[gutenberg_id] = source.set_name

    assert not collisions, "; ".join(collisions)


def test_noise_and_heldout_authors_are_disjoint(sources) -> None:
    """Rule 3. A profile perturbed by an author in run 2 is not an unbiased judge of that author later."""

    def surnames(name: str) -> set[str]:
        return {s.author.split()[-1] for s in sources.sets[name] if s.author}

    overlap = surnames("noise_pool") & surnames("heldout")
    assert not overlap, f"authors in both the noise pool and the held-out set: {sorted(overlap)}"


def test_noise_and_mixture_authors_are_disjoint(sources) -> None:
    """Same reasoning: the spliced-in author must not have shaped the profile that judges the splice."""

    def surnames(name: str) -> set[str]:
        return {s.author.split()[-1] for s in sources.sets[name] if s.author}

    overlap = surnames("noise_pool") & surnames("mixture_sources")
    assert not overlap, f"authors in both the noise pool and the mixture sources: {sorted(overlap)}"


def test_the_noise_pool_is_large_enough_for_the_configured_runs(sources) -> None:
    """Runs 2..M each take a different foreign text, so the pool must hold at least M-1."""
    assert len(sources.sets["noise_pool"]) >= 4, "the pool cannot supply M-1 distinct texts for M=5"


def test_every_noise_text_is_creation_scale(sources) -> None:
    """A noise text enters profile extraction, so its size changes what the profile is computed from.

    The specification injects "one different foreign creation". An epic or a collected edition is not
    one creation: The Faerie Queene at 472,000 words would have been a third of the corpus on its own
    and would have rewritten the profile rather than perturbed it, which is the opposite of what the
    robustness test is for. No such constraint applies to the held-out or mixture sets, which are
    scored rather than profiled.
    """
    from mmlsa.corpus.loader import load_text
    from mmlsa.corpus.normalize import count_words

    oversized = []
    for source in sources.sets["noise_pool"]:
        path = text_path(REPO_ROOT, source)
        if not path.is_file():
            pytest.skip("noise pool not fetched")
        words = count_words(load_text(source, REPO_ROOT))
        if not 10_000 <= words <= 60_000:
            oversized.append(f"{source.id}: {words:,} words")

    assert not oversized, "noise texts outside creation scale: " + "; ".join(oversized)


def test_the_held_out_set_contains_both_expected_labels(sources) -> None:
    """A held-out set of only one class would test nothing but a constant classifier."""
    labels = {s.expected_label for s in sources.sets["heldout"]}

    assert "authentic" in labels
    assert "suspicious" in labels


def test_every_corpus_entry_records_its_paper_title(sources) -> None:
    """The agreement report matches on the reference paper's own wording, not by eye."""
    missing = [s.id for s in sources.sets["texts"] if not s.paper_title]

    assert not missing, f"creations with no paper_title recorded: {missing}"


def test_paper_titles_are_unique(sources) -> None:
    """Two creations mapped to the same row of the paper's table would corrupt the comparison."""
    titles = [s.paper_title for s in sources.sets["texts"]]
    duplicates = sorted({t for t in titles if titles.count(t) > 1})

    assert not duplicates, f"duplicated paper titles: {duplicates}"


# ------------------------------------------------------------------------------- loader failures


def _write(path: Path, mapping: dict) -> Path:
    path.write_text(yaml.safe_dump(mapping, sort_keys=False), encoding="utf-8")
    return path


def test_a_text_declared_in_two_sets_is_rejected(tmp_path: Path) -> None:
    """The loader refuses rather than leaving the collision to be noticed in the results."""
    path = _write(
        tmp_path / "sources.yaml",
        {
            "author_label": "Author",
            "texts": [{"id": "a", "title": "A", "gutenberg_id": 1}],
            "noise_pool": [{"id": "b", "title": "B", "gutenberg_id": 1}],
        },
    )

    with pytest.raises(CorpusError, match="appears in both"):
        load_sources(path)


def test_a_duplicate_id_is_rejected(tmp_path: Path) -> None:
    """Two entries with one id would silently overwrite each other on disk."""
    path = _write(
        tmp_path / "sources.yaml",
        {
            "author_label": "Author",
            "texts": [{"id": "a", "title": "A", "gutenberg_id": 1}],
            "heldout": [{"id": "a", "title": "A again", "gutenberg_id": 2}],
        },
    )

    with pytest.raises(CorpusError, match="declared twice"):
        load_sources(path)


@pytest.mark.parametrize("missing", ["id", "title"])
def test_a_missing_required_field_is_rejected(tmp_path: Path, missing: str) -> None:
    """An entry with no identifier or no title could not be stored or reported."""
    entry = {"id": "a", "title": "A", "gutenberg_id": 1}
    del entry[missing]
    path = _write(tmp_path / "sources.yaml", {"author_label": "Author", "texts": [entry]})

    with pytest.raises(CorpusError, match=missing):
        load_sources(path)


def test_a_locally_authored_text_may_declare_no_gutenberg_origin(tmp_path: Path) -> None:
    """The development fixtures have no external provenance.

    Giving them invented identifiers would put numbers that look like provenance into the manifest,
    so they declare none and the fetcher refuses them instead.
    """
    path = _write(
        tmp_path / "sources.yaml",
        {"author_label": "Author", "texts": [{"id": "a", "title": "A", "gutenberg_id": None}]},
    )

    source = load_sources(path).sets["texts"][0]

    assert source.is_local
    assert source.gutenberg_ids == ()
    assert source.source_urls == ()


def test_fetching_a_locally_authored_text_is_refused(tmp_path: Path) -> None:
    """There is nothing to download, and inventing a request would be worse than an error."""
    from mmlsa.corpus.loader import fetch_text

    path = _write(
        tmp_path / "sources.yaml",
        {"author_label": "Author", "texts": [{"id": "a", "title": "A", "gutenberg_id": None}]},
    )
    source = load_sources(path).sets["texts"][0]

    with pytest.raises(CorpusError, match="must not be fetched"):
        fetch_text(source, tmp_path)


def test_the_development_fixture_corpus_resolves(repo_root: Path) -> None:
    """``configs/mini.yaml`` must actually load, or the fast feedback loop is fiction."""
    from mmlsa.corpus.loader import directories_from_config, load_corpus
    from mmlsa.settings import build_config

    config = build_config(repo_root / "configs" / "mini.yaml")
    sources = load_sources(config.path(config.corpus.sources))
    texts = load_corpus(sources, config.root, directories=directories_from_config(config))

    assert len(texts) == config.corpus.expected_count == 3
    assert all(len(text.split()) > 100 for text in texts.values())
