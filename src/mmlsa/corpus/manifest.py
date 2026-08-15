"""Building and verifying ``data/manifest.json``.

The manifest is the corpus's integrity record: what each text is, how long it is, what its checksum
is, where it came from, and what normalization did to it. ``corpus verify`` compares the files on
disk against it, so that a text edited by accident, a re-download that silently changed edition, or
a normalization rule that quietly stopped firing all surface as a failed check rather than as an
unexplained score three milestones later.

See ``docs/DATA.md`` section 6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mmlsa.corpus.gutenberg import has_residual_marker
from mmlsa.corpus.loader import (
    SET_NAMES,
    CorpusError,
    CorpusSources,
    TextSource,
    text_path,
    word_count_within_band,
)
from mmlsa.corpus.normalize import NORMALIZATION_VERSION, NormalizationReport, count_words
from mmlsa.distance.tokenize import load_function_words
from mmlsa.utils.hashing import hash_text

DEFAULT_WORD_COUNT_TOLERANCE = 0.35
"""How far a measured word count may sit from its declared expectation.

Deliberately loose. The band exists to catch a wrong or truncated file, not to pin an edition:
Gutenberg editions of the same play legitimately differ by a few thousand words in front matter,
stage directions and speech-prefix style.
"""

CORPUS_WORD_RANGE = (1_000_000, 1_150_000)
"""The expected corpus total, in words.

``docs/DATA.md`` section 7 estimates 0.9 to 1.0 million. The assembled corpus measures 1.065
million, and the difference is accounted for rather than tolerated: we deliberately keep speaker
prefixes and stage directions (``docs/OPEN_QUESTIONS.md`` Q4), and those come to 6.7 and 2.8 percent
of the corpus respectively, with act and scene headings a further 0.6. Removing them leaves roughly
956,000 words of spoken text, which is inside the documented estimate.

The band here is therefore on the figure actually being measured, the stored corpus including its
retained apparatus. See ``docs/RESULTS.md``.
"""


@dataclass
class VerificationResult:
    """The outcome of ``corpus verify``: what passed, what failed, and what merely looks odd."""

    checks_run: int = 0
    failures: list[str] = None  # type: ignore[assignment]
    warnings: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.failures = self.failures or []
        self.warnings = self.warnings or []

    @property
    def ok(self) -> bool:
        """Whether every check passed. Warnings do not fail a verification."""
        return not self.failures


def _entry(
    source: TextSource,
    text: str,
    report: NormalizationReport | None,
) -> dict[str, Any]:
    """One manifest record for one text."""
    entry: dict[str, Any] = {
        "id": source.id,
        "title": source.title,
        "gutenberg_ids": list(source.gutenberg_ids),
        "source_urls": list(source.source_urls),
        "sha256": hash_text(text),
        "n_words": count_words(text),
        "n_chars": len(text),
    }
    if source.author:
        entry["author"] = source.author
    if source.paper_title:
        entry["paper_title"] = source.paper_title
    if source.expected_words is not None:
        entry["expected_words"] = source.expected_words
    if source.apocryphal:
        entry["apocryphal"] = True
    if source.expected_label:
        entry["expected_label"] = source.expected_label
    if report is not None:
        entry["normalization"] = {
            "removed_transcriber_notes": report.removed_transcriber_notes,
            "removed_contents": report.removed_contents,
            "removed_persons": report.removed_persons,
            "removed_front_matter_words": report.removed_front_matter_words,
            "front_matter_rule": report.front_matter_rule,
            "notes": report.notes,
        }
    return entry


def build_manifest(
    sources: CorpusSources,
    root: Path,
    texts: dict[str, str],
    reports: dict[str, NormalizationReport] | None = None,
    *,
    function_words_path: str = "data/function_words/en_core_v1.txt",
) -> dict[str, Any]:
    """Assemble the manifest from the texts currently on disk.

    ``speaker_prefixes`` is recorded explicitly because ``docs/DATA.md`` requires the choice to be
    stated rather than implied, and because it is the single normalization decision most likely to
    be questioned by a reader.
    """
    reports = reports or {}
    resolved_words = root / function_words_path
    function_words = load_function_words(str(resolved_words))

    manifest: dict[str, Any] = {
        "generated_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "normalization_version": NORMALIZATION_VERSION,
        "speaker_prefixes": "kept",
        "stage_directions": "kept",
        "function_words": {
            "file": Path(function_words_path).name,
            "sha256": hash_text(resolved_words.read_text(encoding="utf-8")),
            "count": len(function_words),
        },
        "sets": {},
    }

    for name in SET_NAMES:
        entries = []
        for source in sources.sets.get(name, []):
            if source.id not in texts:
                continue
            entries.append(_entry(source, texts[source.id], reports.get(source.id)))
        manifest["sets"][name] = entries

    corpus_entries = manifest["sets"].get("texts", [])
    manifest["totals"] = {
        "n_texts": len(corpus_entries),
        "n_words": sum(e["n_words"] for e in corpus_entries),
        "n_chars": sum(e["n_chars"] for e in corpus_entries),
    }
    return manifest


def write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    """Write the manifest as sorted, indented JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def read_manifest(path: Path) -> dict[str, Any]:
    """Read the manifest, with a clear error if it has not been generated yet."""
    if not path.is_file():
        raise CorpusError(f"manifest not found at {path}. Run 'mmlsa corpus fetch' first.")
    return json.loads(path.read_text(encoding="utf-8"))


def verify(
    sources: CorpusSources,
    root: Path,
    manifest: dict[str, Any],
    *,
    expected_count: int = 49,
    word_count_tolerance: float = DEFAULT_WORD_COUNT_TOLERANCE,
) -> VerificationResult:
    """Check every text on disk against the manifest and against the specification's expectations.

    Failures are things that make the corpus wrong. Warnings are things worth a human's attention
    that do not invalidate a run, such as a word count outside its declared band, which is as likely
    to mean the estimate was rough as that the text is wrong.
    """
    result = VerificationResult()

    for name in SET_NAMES:
        entries = {e["id"]: e for e in manifest.get("sets", {}).get(name, [])}
        declared = sources.sets.get(name, [])

        for source in declared:
            result.checks_run += 1
            path = text_path(root, source)

            if not path.is_file():
                result.failures.append(f"{source.id}: normalized text missing at {path}")
                continue

            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                result.failures.append(f"{source.id}: not valid UTF-8 ({exc})")
                continue

            entry = entries.get(source.id)
            if entry is None:
                result.failures.append(f"{source.id}: on disk but absent from the manifest")
                continue

            digest = hash_text(text)
            if digest != entry["sha256"]:
                result.failures.append(
                    f"{source.id}: checksum drift. The file has changed since the manifest was "
                    f"generated (manifest {entry['sha256'][:12]}, file {digest[:12]})"
                )

            if has_residual_marker(text):
                result.failures.append(
                    f"{source.id}: Project Gutenberg boilerplate survives in the normalized text"
                )

            words = count_words(text)
            if words != entry["n_words"]:
                result.failures.append(
                    f"{source.id}: word count differs from the manifest "
                    f"({words} on disk, {entry['n_words']} recorded)"
                )
            if not word_count_within_band(words, source.expected_words, word_count_tolerance):
                result.warnings.append(
                    f"{source.id}: {words} words, expected about {source.expected_words} "
                    f"(outside {word_count_tolerance:.0%})"
                )
            if words == 0:
                result.failures.append(f"{source.id}: normalized text is empty")

        for text_id in entries:
            if not any(source.id == text_id for source in declared):
                result.failures.append(f"{text_id}: in the manifest but no longer declared")

    corpus = manifest.get("sets", {}).get("texts", [])
    result.checks_run += 1
    if len(corpus) != expected_count:
        result.failures.append(
            f"the corpus holds {len(corpus)} creations, expected {expected_count}"
        )

    total = manifest.get("totals", {}).get("n_words", 0)
    result.checks_run += 1
    low, high = CORPUS_WORD_RANGE
    if not low <= total <= high:
        result.warnings.append(
            f"the corpus totals {total:,} words, outside the expected {low:,} to {high:,}"
        )

    return result
