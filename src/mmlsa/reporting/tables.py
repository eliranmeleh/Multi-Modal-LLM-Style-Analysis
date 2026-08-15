"""Result tables.

Every number that reaches the report is generated here from run artifacts. Nothing is transcribed
by hand, which is the only way a table and the run that produced it stay in agreement.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from mmlsa.pipeline.classify import AUTHENTIC, Classification, ThresholdResult
from mmlsa.pipeline.score import CreationScore

SCORES_COLUMNS = [
    "creation_id",
    "title",
    "n_chunks",
    "score_mean",
    "score_std",
    "label",
    "borderline",
    "unreliable",
    "unreliable_reason",
    "score_length_weighted",
]


def scores_frame(
    creations: Sequence[CreationScore],
    classification: Classification | None = None,
    *,
    titles: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Assemble the per-creation results table.

    Unscorable creations are included with an empty score and their reason, rather than dropped:
    a creation that vanished from the output is indistinguishable from one that was never in the
    corpus.
    """
    titles = titles or {}
    rows: list[dict[str, Any]] = []

    for creation in sorted(creations, key=lambda c: c.creation_id):
        row: dict[str, Any] = {
            "creation_id": creation.creation_id,
            "title": titles.get(creation.creation_id, ""),
            "n_chunks": _first_chunk_count(creation),
            "score_mean": creation.score,
            "score_std": creation.score_std,
            "label": "",
            "borderline": False,
            "unreliable": creation.unreliable,
            "unreliable_reason": creation.unreliable_reason,
            "score_length_weighted": creation.length_weighted_score,
        }
        for run_index, value in enumerate(creation.per_run, start=1):
            row[f"s_{run_index}"] = value

        if classification is not None and creation.creation_id in classification.labels:
            row["label"] = classification.labels[creation.creation_id]
            row["borderline"] = creation.creation_id in classification.borderline

        rows.append(row)

    frame = pd.DataFrame(rows)
    run_columns = sorted(
        (c for c in frame.columns if c.startswith("s_")),
        key=lambda c: int(c.split("_", 1)[1]),
    )
    ordered = [*SCORES_COLUMNS[:5], *run_columns, *SCORES_COLUMNS[5:]]
    return frame[[c for c in ordered if c in frame.columns]]


def _first_chunk_count(creation: CreationScore) -> int | None:
    """The chunk count of the first run, which is the same in every run for a fixed ``P``."""
    counts = creation.diagnostics.get("n_chunks_total")
    return int(counts[0]) if isinstance(counts, list) and counts else None


def write_scores_csv(frame: pd.DataFrame, path: Path) -> Path:
    """Write the per-creation results table."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)
    return path


def write_threshold_json(
    threshold: ThresholdResult,
    classification: Classification,
    path: Path,
) -> Path:
    """Write the threshold, its diagnostics and the resulting sets.

    The flags are written even when empty, so the absence of a warning is recorded as a positive
    fact rather than inferred from a missing key.
    """
    payload = {
        "tau": threshold.tau,
        "method": threshold.method,
        "between_class_variance": threshold.between_class_variance,
        "flagged": threshold.flagged,
        "diagnostics": _jsonable(threshold.diagnostics),
        "n_suspicious": len(classification.suspicious),
        "n_authentic": len(classification.authentic),
        "suspicious": sorted(classification.suspicious),
        "borderline": sorted(classification.borderline),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _jsonable(value: Any) -> Any:
    """Convert numpy scalars and containers into plain JSON-serializable data."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, frozenset, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "item") and callable(value.item):
        return value.item()
    return value


def suspicious_table(frame: pd.DataFrame) -> pd.DataFrame:
    """The suspicious set, sorted by score descending, as it appears in the report.

    Reads the labels already written into the frame rather than taking the classification again, so
    the table can never disagree with the CSV it was derived from.
    """
    suspicious = frame[(frame["label"] != AUTHENTIC) & (frame["label"] != "")].copy()
    return suspicious.sort_values("score_mean", ascending=False).reset_index(drop=True)


def to_markdown(frame: pd.DataFrame, *, decimals: int = 4) -> str:
    """Render a table as Markdown for inclusion in the report.

    Written out rather than delegated to ``DataFrame.to_markdown``, which needs ``tabulate``. The
    approved book lists the toolchain and examiners read that table, so a dependency is not worth
    adding for a formatting convenience.
    """

    def cell(value: Any) -> str:
        if value is None or (isinstance(value, float) and value != value):
            return ""
        if isinstance(value, float):
            return f"{value:.{decimals}f}"
        return str(value)

    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    separator = "| " + " | ".join("---" for _ in frame.columns) + " |"
    rows = [
        "| " + " | ".join(cell(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    ]
    return "\n".join([header, separator, *rows])
