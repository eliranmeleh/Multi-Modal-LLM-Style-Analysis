"""Reading ``corpus_sources.yaml``, fetching what it names, and loading the normalized result.

The four text sets are kept as one declaration in one file so that the disjointness rules in
``docs/DATA.md`` section 1.1 can be checked mechanically. A text that is used both as injected noise
and as a held-out test subject turns a validation test into a self-fulfilling result, and that is
the kind of mistake that is invisible in the output.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mmlsa.corpus.gutenberg import GutenbergError, download, strip_boilerplate
from mmlsa.corpus.normalize import NormalizationReport, count_words, normalize

SET_NAMES = ("texts", "noise_pool", "heldout", "mixture_sources")
SET_DIRECTORIES = {
    "texts": "corpus",
    "noise_pool": "noise_pool",
    "heldout": "heldout",
    "mixture_sources": "mixture_sources",
}


class CorpusError(Exception):
    """Raised for a malformed source declaration or a text that fails its integrity checks."""


@dataclass(frozen=True)
class TextSource:
    """One declared text: what it is, where it comes from, and what set it belongs to."""

    id: str
    title: str
    gutenberg_ids: tuple[int, ...]
    set_name: str
    author: str = ""
    paper_title: str = ""
    expected_words: int | None = None
    apocryphal: bool = False
    expected_label: str = ""

    @property
    def is_composite(self) -> bool:
        """Whether this creation is assembled from more than one Gutenberg file."""
        return len(self.gutenberg_ids) > 1

    @property
    def source_urls(self) -> tuple[str, ...]:
        """The canonical landing pages, recorded as provenance in the manifest."""
        return tuple(f"https://www.gutenberg.org/ebooks/{gid}" for gid in self.gutenberg_ids)


@dataclass
class CorpusSources:
    """Every declared text, grouped by set."""

    author_label: str
    sets: dict[str, list[TextSource]] = field(default_factory=dict)

    def all_texts(self) -> Iterator[TextSource]:
        """Every text in every set, in declaration order."""
        for name in SET_NAMES:
            yield from self.sets.get(name, [])

    def by_id(self, text_id: str) -> TextSource:
        """Look up one text by its identifier."""
        for source in self.all_texts():
            if source.id == text_id:
                return source
        raise CorpusError(f"no text declared with id '{text_id}'")


def _parse_entry(raw: dict[str, Any], set_name: str) -> TextSource:
    """Build a ``TextSource`` from one YAML entry, failing loudly on a missing required field."""
    for required in ("id", "title", "gutenberg_id"):
        if required not in raw:
            raise CorpusError(f"{set_name} entry is missing '{required}': {raw}")

    identifiers = raw["gutenberg_id"]
    identifiers = identifiers if isinstance(identifiers, list) else [identifiers]

    return TextSource(
        id=str(raw["id"]),
        title=str(raw["title"]),
        gutenberg_ids=tuple(int(g) for g in identifiers),
        set_name=set_name,
        author=str(raw.get("author", "")),
        paper_title=str(raw.get("paper_title", "")),
        expected_words=raw.get("expected_words"),
        apocryphal=bool(raw.get("apocryphal", False)),
        expected_label=str(raw.get("expected_label", "")),
    )


def load_sources(path: Path) -> CorpusSources:
    """Read and validate ``corpus_sources.yaml``.

    Validation here is structural: required fields, unique identifiers, and the hard disjointness
    rule that no text appears in two sets. Word counts are checked later, against the fetched text.
    """
    if not path.is_file():
        raise CorpusError(f"corpus sources file not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise CorpusError(f"{path} must contain a mapping at the top level")

    sources = CorpusSources(author_label=str(raw.get("author_label", "")))
    for name in SET_NAMES:
        entries = raw.get(name) or []
        if not isinstance(entries, list):
            raise CorpusError(f"{path}: '{name}' must be a list")
        sources.sets[name] = [_parse_entry(entry, name) for entry in entries]

    _check_disjointness(sources, path)
    return sources


def _check_disjointness(sources: CorpusSources, path: Path) -> None:
    """Enforce ``docs/DATA.md`` section 1.1: no identifier and no Gutenberg text in two sets."""
    seen_ids: dict[str, str] = {}
    seen_gutenberg: dict[int, str] = {}

    for source in sources.all_texts():
        if source.id in seen_ids:
            raise CorpusError(
                f"{path}: id '{source.id}' is declared twice "
                f"(in '{seen_ids[source.id]}' and '{source.set_name}')"
            )
        seen_ids[source.id] = source.set_name

        for gutenberg_id in source.gutenberg_ids:
            if gutenberg_id in seen_gutenberg:
                raise CorpusError(
                    f"{path}: Gutenberg text {gutenberg_id} appears in both "
                    f"'{seen_gutenberg[gutenberg_id]}' and '{source.set_name}'. A text used as "
                    "noise must never also be a held-out subject or a mixture source."
                )
            seen_gutenberg[gutenberg_id] = source.set_name


def text_path(root: Path, source: TextSource) -> Path:
    """Where the normalized text for one source is stored."""
    return root / "data" / SET_DIRECTORIES[source.set_name] / f"{source.id}.txt"


def raw_path(root: Path, gutenberg_id: int) -> Path:
    """Where the unmodified download is cached, before normalization. Git-ignored."""
    return root / "data" / "_raw" / f"{gutenberg_id}.txt"


def fetch_text(
    source: TextSource,
    root: Path,
    *,
    force: bool = False,
    pause_seconds: float = 1.0,
) -> tuple[str, NormalizationReport]:
    """Download, strip boilerplate and normalize one declared text.

    The raw download is cached under ``data/_raw/`` so that re-normalizing after a rule change costs
    no network traffic, and so that the exact bytes that were downloaded remain inspectable.

    A composite creation is assembled by concatenating its parts in declared order, each stripped
    and normalized independently, separated by a blank line.
    """
    parts: list[str] = []
    report = NormalizationReport()

    for gutenberg_id in source.gutenberg_ids:
        cached = raw_path(root, gutenberg_id)
        if force or not cached.is_file():
            raw = download(gutenberg_id, pause_seconds=pause_seconds)
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(raw, encoding="utf-8")
            time.sleep(pause_seconds)
        else:
            raw = cached.read_text(encoding="utf-8")

        try:
            body = strip_boilerplate(raw, source=f"{source.id} (Gutenberg {gutenberg_id})")
        except GutenbergError as exc:
            raise CorpusError(str(exc)) from exc

        normalized, part_report = normalize(body)
        parts.append(normalized)

        report.removed_transcriber_notes += part_report.removed_transcriber_notes
        report.removed_contents = report.removed_contents or part_report.removed_contents
        report.removed_persons = report.removed_persons or part_report.removed_persons
        report.removed_front_matter_words += part_report.removed_front_matter_words
        if part_report.front_matter_rule != "none":
            report.front_matter_rule = (
                part_report.front_matter_rule
                if report.front_matter_rule in ("none", part_report.front_matter_rule)
                else "mixed"
            )
        report.notes.extend(part_report.notes)

    return "\n\n".join(parts).strip() + "\n", report


def write_text(source: TextSource, root: Path, text: str) -> Path:
    """Store a normalized text and return where it was written."""
    destination = text_path(root, source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text, encoding="utf-8", newline="\n")
    return destination


def load_text(source: TextSource, root: Path) -> str:
    """Read one normalized text from disk."""
    path = text_path(root, source)
    if not path.is_file():
        raise CorpusError(f"text '{source.id}' has not been fetched yet (expected at {path})")
    return path.read_text(encoding="utf-8")


def load_corpus(
    sources: CorpusSources,
    root: Path,
    *,
    include_ids: list[str] | None = None,
    exclude_ids: list[str] | None = None,
) -> dict[str, str]:
    """Load the target corpus as ``{creation_id: normalized text}``, honouring the config subset.

    Returned in declaration order, which is stable across machines and filesystems. An
    ``include_ids`` entry that matches nothing is an error rather than a silently smaller run.
    """
    excluded = set(exclude_ids or [])
    selected = sources.sets["texts"]

    if include_ids is not None:
        declared = {source.id for source in selected}
        unknown = [text_id for text_id in include_ids if text_id not in declared]
        if unknown:
            raise CorpusError(
                f"corpus.include_ids names texts that are not in the corpus: {', '.join(unknown)}"
            )
        wanted = set(include_ids)
        selected = [source for source in selected if source.id in wanted]

    return {source.id: load_text(source, root) for source in selected if source.id not in excluded}


def word_count_within_band(actual: int, expected: int | None, tolerance: float) -> bool:
    """Whether a measured word count sits inside its declared sanity band."""
    if expected is None:
        return True
    return abs(actual - expected) <= tolerance * expected


__all__ = [
    "CorpusError",
    "CorpusSources",
    "TextSource",
    "count_words",
    "fetch_text",
    "load_corpus",
    "load_sources",
    "load_text",
    "raw_path",
    "text_path",
    "word_count_within_band",
    "write_text",
]
