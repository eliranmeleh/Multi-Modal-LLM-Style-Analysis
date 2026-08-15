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
| **Current milestone** | M8 — orchestrator, `M` runs, noise injection |
| **Pipeline state** | **All six steps are built and run end to end offline.** `tests/integration/test_pipeline_end_to_end.py` takes the mini corpus from raw text to a classified `scores.csv` with no provider. What is missing is the orchestrator that does this from one command, with the `M`-run loop, noise injection and immutable run directories. |
| **Quality gates** | `ruff check`, `ruff format --check`, `mypy src` all clean; 488 tests pass; 88 per cent coverage overall |
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
| M5 | Provider protocol, cache, ledger, runner | **done** |
| M6 | Step 1, profile extraction | **done** |
| M7 | Step 3, rewriting | **done** |
| M8 | Orchestrator, `M` runs, noise injection | next |
| M9 | First real call, provider comparison | not started |
| M10 | Stage 1, proof of concept | not started |
| M11 | Stage 2, reproducibility and sensitivity | not started |
| M12 | Stage 3, full corpus run | not started |
| M13 | Stage 5, control experiment | not started |
| M14 | Validation test suite | not started |
| M15 | Reporting and finalization | not started |
| M16 | Distance-metric comparison (optional) | not started |
| M17 | Iterative purification (optional) | not started |

**Phase 0 is complete and Phase 1 is underway.** The ordering principle in `docs/PLAN.md` worked as
intended: the measurement code was built and tested before anything touched a provider, and the LLM
layer was then built and tested without one either. Everything so far runs offline with no API key.

What works end to end today: load the corpus, chunk it, send every chunk through the cache, the rate
limiter and the runner to `FakeProvider`, measure the distance, aggregate, threshold, classify and
plot. What is missing is only the two steps that render a real prompt: profile extraction (M6) and
rewriting (M7).

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
| `src/mmlsa/llm/` | Provider protocol, content-addressed cache, append-only ledger, bounded-concurrency runner, `FakeProvider` and `ReplayProvider` |
| `src/mmlsa/prompts/` | The book's prompt templates verbatim, versioned; rendering and profile serialization |
| `src/mmlsa/pipeline/profile.py` | Step 1: token estimation, deterministic packing, `k` calls, the merge call |
| `src/mmlsa/pipeline/rewrite.py` | Step 3: cleaning, the four validation checks, batched retries, failure accounting |
| `tests/fixtures/mini_corpus/` | Three short locally authored texts driving `configs/mini.yaml` |
| `tests/integration/test_pipeline_end_to_end.py` | All six steps over the mini corpus, no provider |
| `data/function_words/en_core_v1.txt` | The versioned 127-entry list |

## Next actions

In order. Keep this list short; three to five items.

1. **M8**, the orchestrator: the `M`-run loop, deterministic noise selection, immutable run
   directories, and `mmlsa run` actually running. **Its tests must inject noise** — see the note in
   `docs/PLAN.md` under M8. Without noise the `M` runs are byte-identical under `FakeProvider`, so
   the averaging in Step 5 would be tested against `M` copies of one number.
4. **Get a Gemini API key** and put it in `.env`. Nothing before M9 needs it, but it is the one
   thing on this list that cannot be done by writing code.
5. **Ask the supervisors Q10 and Q12** (see below). Q10 in particular has to be settled before any
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
