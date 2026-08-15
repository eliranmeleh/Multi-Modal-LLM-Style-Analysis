"""The call ledger.

Non-functional requirement Auditability (R2). The ledger is the only record that a published number
came from the calls it claims to have come from, so its completeness is checked, not assumed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mmlsa.llm.base import LLMRequest, LLMResponse
from mmlsa.llm.ledger import (
    LEDGER_SCHEMA_VERSION,
    REQUIRED_FIELDS,
    Ledger,
    build_entry,
    read_ledger,
    summarize,
    validate_line,
)
from mmlsa.utils.hashing import hash_text

REQUEST = LLMRequest(prompt="rewrite this passage", tag="rewrite", max_output_tokens=512)
RESPONSE = LLMResponse(
    text="rewritten passage",
    model_id="fake-1",
    model_version="fake-1-deterministic",
    input_tokens=3,
    output_tokens=2,
    latency_ms=7,
)


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    """A ledger for a single run."""
    return Ledger(tmp_path / "runs" / "r1" / "calls.jsonl", run_id="r1")


def entry(**overrides):
    """A valid entry, with fields overridable per test."""
    defaults = {
        "run_id": "r1",
        "cache_key": "a" * 64,
        "request": REQUEST,
        "provider": "fake",
        "model_id": "fake-1",
        "cached": False,
        "status": "ok",
        "response": RESPONSE,
    }
    return build_entry(**(defaults | overrides))


# ------------------------------------------------------------------------------ what is written


def test_an_entry_records_everything_the_requirement_names(ledger: Ledger) -> None:
    """R2: prompt, response, model id, model version, parameters, tokens, latency, timestamp."""
    ledger.append(entry())
    line = read_ledger(ledger.path)[0]

    assert line["prompt"] == REQUEST.prompt
    assert line["response"] == RESPONSE.text
    assert line["model_id"] == "fake-1"
    assert line["model_version"] == RESPONSE.model_version
    assert line["temperature"] == REQUEST.temperature
    assert line["max_output_tokens"] == REQUEST.max_output_tokens
    assert line["input_tokens"] == 3
    assert line["output_tokens"] == 2
    assert line["latency_ms"] == 7
    assert line["ts_utc"].endswith("Z")


def test_the_full_prompt_is_written_not_only_its_hash(ledger: Ledger) -> None:
    """docs/PROMPTS.md section 6 commits the project to publishing the actual bytes sent."""
    long_prompt = "Passage to rewrite:\n" + " ".join(f"word{i}" for i in range(500))
    ledger.append(entry(request=LLMRequest(prompt=long_prompt, tag="rewrite")))
    line = read_ledger(ledger.path)[0]

    assert line["prompt"] == long_prompt
    assert line["prompt_sha256"] == hash_text(long_prompt)


def test_provenance_links_a_line_back_to_a_chunk(ledger: Ledger) -> None:
    """R7: every score traces to the individual calls that produced it."""
    ledger.append(entry(creation_id="text_a", chunk_index=17, run_index=2))
    line = read_ledger(ledger.path)[0]

    assert (line["creation_id"], line["chunk_index"], line["run_index"]) == ("text_a", 17, 2)


def test_a_failed_call_records_the_error_and_no_response(ledger: Ledger) -> None:
    """A failure has to be as visible in the record as a success."""
    ledger.append(
        entry(
            status="failed",
            response=None,
            error="rate limited",
            error_class="TransientProviderError",
        )
    )
    line = read_ledger(ledger.path)[0]

    assert line["status"] == "failed"
    assert line["error"] == "rate limited"
    assert line["error_class"] == "TransientProviderError"
    assert line["response"] == ""


# ---------------------------------------------------------------------------------- the schema


def test_every_required_field_is_present(ledger: Ledger) -> None:
    """The schema the tests and the report both depend on."""
    ledger.append(entry())
    line = read_ledger(ledger.path)[0]

    for name in REQUIRED_FIELDS:
        assert name in line, f"missing {name}"
    assert line["schema_version"] == LEDGER_SCHEMA_VERSION


def test_a_valid_line_validates(ledger: Ledger) -> None:
    """The control for the negative cases below."""
    ledger.append(entry())

    assert validate_line(read_ledger(ledger.path)[0]) == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ({"schema_version": 99}, "schema_version"),
        ({"status": "maybe"}, "status"),
        ({"cached": "yes"}, "cached"),
        ({"prompt_sha256": "0" * 64}, "prompt_sha256"),
    ],
)
def test_a_malformed_line_is_rejected(ledger: Ledger, mutation: dict, expected: str) -> None:
    """A validator that cannot fail would certify a broken ledger."""
    ledger.append(entry())
    line = read_ledger(ledger.path)[0] | mutation

    problems = validate_line(line)
    assert problems
    assert any(expected in problem for problem in problems)


def test_a_missing_field_is_reported_by_name(ledger: Ledger) -> None:
    """So a schema change points at what to fix."""
    ledger.append(entry())
    line = read_ledger(ledger.path)[0]
    del line["cache_key"]

    assert any("cache_key" in problem for problem in validate_line(line))


def test_a_successful_call_without_a_response_hash_is_rejected(ledger: Ledger) -> None:
    """Catches an entry built with status ok but no response attached."""
    ledger.append(entry())
    line = read_ledger(ledger.path)[0] | {"response_sha256": ""}

    assert any("response hash" in problem for problem in validate_line(line))


# -------------------------------------------------------------------------------- append-only


def test_lines_accumulate_and_are_never_rewritten(ledger: Ledger) -> None:
    """Append-only, so a resumed run extends the record rather than replacing it."""
    for index in range(3):
        ledger.append(entry(creation_id=f"text_{index}"))

    assert len(read_ledger(ledger.path)) == 3
    assert ledger.count == 3

    reopened = Ledger(ledger.path, run_id="r1")
    reopened.append(entry(creation_id="text_3"))

    assert len(read_ledger(ledger.path)) == 4


def test_each_line_is_independently_parseable(ledger: Ledger) -> None:
    """JSON Lines, so a partially written file is still readable up to its last complete line."""
    ledger.append(entry())
    ledger.append(entry(creation_id="text_b"))

    for line in ledger.path.read_text(encoding="utf-8").splitlines():
        assert json.loads(line)


def test_a_trailing_partial_line_is_tolerated(ledger: Ledger) -> None:
    """A run killed mid-write leaves one incomplete line; everything before it is intact."""
    ledger.append(entry())
    ledger.append(entry(creation_id="text_b"))
    with ledger.path.open("a", encoding="utf-8") as stream:
        stream.write('{"partial": tru')

    assert len(read_ledger(ledger.path)) == 2


def test_a_corrupt_line_in_the_middle_is_not_silently_skipped(ledger: Ledger) -> None:
    """Tolerating a truncated tail is recovery; tolerating a hole would be hiding data loss."""
    ledger.append(entry())
    with ledger.path.open("a", encoding="utf-8") as stream:
        stream.write("{ not json\n")
    ledger.append(entry(creation_id="text_b"))

    with pytest.raises(json.JSONDecodeError):
        read_ledger(ledger.path)


def test_reading_an_absent_ledger_gives_nothing(tmp_path: Path) -> None:
    """A run that has not started yet has no calls, which is not an error."""
    assert read_ledger(tmp_path / "never.jsonl") == []


def test_concurrent_appends_do_not_interleave(tmp_path: Path) -> None:
    """The runner writes from a worker pool; a torn line would corrupt the audit trail."""
    from concurrent.futures import ThreadPoolExecutor

    ledger = Ledger(tmp_path / "calls.jsonl", run_id="r1")
    long_prompt = "x " * 2000

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda index: ledger.append(
                    entry(
                        request=LLMRequest(prompt=f"{index} {long_prompt}"), creation_id=f"t{index}"
                    )
                ),
                range(64),
            )
        )

    lines = read_ledger(ledger.path)
    assert len(lines) == 64
    assert len({line["creation_id"] for line in lines}) == 64


# ------------------------------------------------------------------------------------ summary


def test_the_summary_separates_cached_from_live(ledger: Ledger) -> None:
    """Cache hits are logged too, and the report needs to tell the two apart."""
    ledger.append(entry(cached=False))
    ledger.append(entry(cached=True, creation_id="text_b"))
    ledger.append(entry(cached=True, creation_id="text_c"))
    ledger.append(entry(status="failed", response=None, cached=False, creation_id="text_d"))

    summary = summarize(read_ledger(ledger.path))

    assert summary.total == 4
    assert summary.cached == 2
    assert summary.live == 2
    assert summary.failed == 1


def test_the_summary_totals_tokens_and_groups_by_tag(ledger: Ledger) -> None:
    """What a run report states about scale."""
    ledger.append(entry())
    ledger.append(entry(request=LLMRequest(prompt="p", tag="profile"), creation_id="text_b"))

    summary = summarize(read_ledger(ledger.path))

    assert summary.input_tokens == 6
    assert summary.output_tokens == 4
    assert summary.by_tag == {"rewrite": 1, "profile": 1}
