# STATUS

**The live board. Read this first in every session; update it before ending one.**

This file answers three questions and nothing else: where we are, what is next, what is blocked.
History belongs in `docs/SESSION_LOG.md`, not here. Findings belong in `docs/RESULTS.md`.

---

## At a glance

| | |
|---|---|
| **Last updated** | 2026-08-15 |
| **Phase** | B — implementation |
| **Current milestone** | M5 — provider protocol, cache, ledger, runner |
| **Pipeline state** | Phase 0 complete. The corpus is assembled and verified, and everything that does not need an LLM is built and tested: chunking, FWED, aggregation, thresholding, result artifacts. No LLM code yet, by design. |
| **Quality gates** | `ruff check`, `ruff format --check`, `mypy src` all clean; 291 tests pass |
| **Corpus** | 49 creations, 1,065,092 words, `corpus verify` passes 70 checks |
| **LLM provider** | none wired yet. Plan: Gemini free tier first (`llm.provider: gemini`), swap later by one config key |
| **API key present** | no. Not needed before M9 |
| **Blocked on** | nothing |

## Milestone board

Mirrors `docs/PLAN.md`. That file holds the acceptance criteria; this is the glance view.

| | Milestone | State |
|---|---|---|
| M0 | Repository skeleton | **done** (CI green pending first push) |
| M1 | Config and logging | **done** |
| M2 | Corpus acquisition and normalization | **done** |
| M3 | Chunking, tokenizer and FWED | **done**, including the corpus-wide properties |
| M4 | Aggregation and exact Otsu | **done** |
| M5 | Provider protocol, cache, ledger, runner | next |
| M6 | Step 1, profile extraction | not started |
| M7 | Step 3, rewriting | not started |
| M8 | Orchestrator, `M` runs, noise injection | not started |
| M9 | First real call, provider comparison | not started |
| M10 | Stage 1, proof of concept | not started |
| M11 | Stage 2, reproducibility and sensitivity | not started |
| M12 | Stage 3, full corpus run | not started |
| M13 | Stage 5, control experiment | not started |
| M14 | Validation test suite | not started |
| M15 | Reporting and finalization | not started |
| M16 | Distance-metric comparison (optional) | not started |
| M17 | Iterative purification (optional) | not started |

**Phase 0 is complete.** Everything through M4 is offline and needed no API key, which is the
ordering principle in `docs/PLAN.md` working as intended: the measurement code was built and tested
before anything touched a provider. The pipeline can chunk the real corpus, measure a distance,
aggregate, threshold, classify and plot. What it cannot yet do is produce a rewrite to measure
against, which is what Phase 1 adds.

## What exists now

| Path | What it does |
|---|---|
| `src/mmlsa/config.py`, `settings.py` | Pydantic model, `extends` resolution, config hashing, four-layer precedence |
| `src/mmlsa/chunking.py` | Step 2, full coverage, trailing chunk kept |
| `src/mmlsa/distance/` | Step 4: tokenizer, FWED, registry |
| `src/mmlsa/pipeline/score.py` | Step 5, mean over chunks then over runs, failure accounting |
| `src/mmlsa/pipeline/classify.py` | Step 6, exact Otsu, skimage cross-check, GMM fallback, bimodality diagnostics |
| `src/mmlsa/reporting/` | `scores.csv`, `threshold.json`, sorted scatter, histogram, run variance |
| `src/mmlsa/corpus/` | Gutenberg fetching, boilerplate stripping, normalization, manifest and verification |
| `data/corpus/` | The 49 normalized creations, committed |
| `data/manifest.json` | Checksums, word counts, provenance, and what normalization removed per text |
| `data/function_words/en_core_v1.txt` | The versioned 127-entry list |

## Next actions

In order. Keep this list short; three to five items.

1. **M5**, the provider protocol, cache, ledger and runner. This is the load-bearing piece of the
   architecture: resumability, reproducibility and free re-runs all fall out of it. Read
   `docs/ARCHITECTURE.md` section 4 before writing any of it. `FakeProvider` must produce
   non-trivial, deterministic rewrites, or every downstream delta is zero and the integration tests
   prove nothing.
2. **Get a Gemini API key** and put it in `.env`. Nothing before M9 needs it, but it is the one
   thing on this list that cannot be done by writing code.
3. **M6 and M7**, profile extraction and rewriting, both against `FakeProvider`.
4. **Ask the supervisors Q10 and Q12** (see below). Q10 in particular has to be settled before any
   run of record.

## Blocked / waiting on

| Item | Waiting on | Since |
|---|---|---|
| Supervisor confirmation of the profile merge call | next meeting; `docs/OPEN_QUESTIONS.md` Q1 | 2026-08-15 |
| **Whether the function-word list should gain wh-adverbs** | next meeting; `docs/OPEN_QUESTIONS.md` Q10. Settle this **before** M10: changing the list changes every delta ever computed | 2026-08-15 |
| **The exact Gutenberg editions the reference paper used** | next meeting; `docs/OPEN_QUESTIONS.md` Q12. The supervisors are the paper's authors, so this is a five-minute question that removes a permanent caveat from the agreement report | 2026-08-15 |

## Environment

Facts that are easy to lose between sessions.

| | |
|---|---|
| Repository | `.../Desktop/Study/sem7/proj/Multi-Modal-LLM-Style-Analysis` |
| Remote | `https://github.com/eliranmeleh/Multi-Modal-LLM-Style-Analysis` |
| Python | 3.11.15, provisioned by `uv` into `.venv`. The system Python is 3.12 and is **not** used |
| Setup | `uv venv --python 3.11 .venv` then `uv pip install --python .venv -e ".[dev]"` |
| Run anything | `.venv/Scripts/python.exe -m mmlsa --help` (Windows) |
| Quality gate | `ruff check . && ruff format --check . && mypy src && pytest -q` |
| Secrets | `.env`, git-ignored, created from `.env.example` |

**Two local quirks worth remembering.**

*OneDrive.* The repository sits inside a synced folder. `pytest`'s cache is disabled in
`pyproject.toml` because OneDrive intermittently blocks its atomic rename. Before the first wide run,
point `llm.cache_dir` at a path outside OneDrive: a full run writes roughly 7,500 small cache files
and syncing them is pure waste.

*Python.* `uv` supplies 3.11 because the approved book's tools table names it. Do not "fix" a version
error by widening `requires-python`; activate the venv instead.

## Conventions for keeping this file honest

- A milestone moves to **done** only when its acceptance criterion in `docs/PLAN.md` demonstrably
  passes, not when the code exists. M3 above is the worked example of saying so.
- If something is half-finished, say so here in one line rather than leaving it implied.
- Never record a measurement here. Measurements go to `docs/RESULTS.md` with the run id that produced
  them.
