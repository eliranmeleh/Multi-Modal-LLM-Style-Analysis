# STATUS

**The live board. Read this first in every session; update it before ending one.**

This file answers three questions and nothing else: where we are, what is next, what is blocked.
History belongs in `docs/SESSION_LOG.md`, not here. Findings belong in `docs/RESULTS.md`.

---

## At a glance

| | |
|---|---|
| **Last updated** | 2026-08-16 |
| **Phase** | B — implementation |
| **Current milestone** | M9 — first real call and provider validation |
| **Pipeline state** | **The pipeline is finished, and all three live backends are wired.** `mmlsa run --config configs/mini.yaml` takes the corpus through all six steps, `M` times, with noise injection, and writes a complete immutable run directory. Everything from here is measurement, and it needs a key. |
| **Quality gates** | `ruff check`, `ruff format --check`, `mypy src` all clean; 592 tests pass; 90 per cent coverage overall, 98 per cent on `llm/providers/` |
| **Corpus** | 49 creations, 1,065,092 words, `corpus verify` passes 70 checks |
| **LLM provider** | `gemini`, `openai` and `anthropic` implemented and registered, each behind its own optional extra. Default `llm.provider: gemini`, default model `gemini-2.5-flash` (free tier). Swapping is one config key |
| **API key present** | **no — and this is the only blocker.** Every line of code M9 needs is written and tested offline |
| **Blocked on** | an API key. `pip install -e ".[gemini]"`, put `GEMINI_API_KEY` in `.env`, and M9 can start |

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
| M8 | Orchestrator, `M` runs, noise injection | **done** |
| M9 | First real call, provider comparison | **half done.** The three backends are implemented, registered and tested offline. The milestone's deliverable is a *measured* comparison, so it stays open until a key exists |
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
layer was then built and tested without one either. Everything so far runs offline with no API key —
including the three live adapters, whose SDKs are stubbed in the tests.

What works end to end today: load the corpus, chunk it, send every chunk through the cache, the rate
limiter and the runner, measure the distance, aggregate, threshold, classify and plot. What has never
happened is a single real request. Until one does, no claim about the method is evidence.

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
| `src/mmlsa/llm/providers/_live.py` | What the three live backends share: keys from the environment only, optional-SDK loading, failure classification, and the refusal of an empty completion |
| `src/mmlsa/llm/providers/{gemini,openai,anthropic}.py` | The three backends named in the book, each with a model table recording context window, whether `temperature` can be sent, and how to hold reasoning down |
| `tests/contract/test_live_providers.py` | All three exercised against stub SDKs: 61 tests, no network |
| `src/mmlsa/prompts/` | The book's prompt templates verbatim, versioned; rendering and profile serialization |
| `src/mmlsa/pipeline/profile.py` | Step 1: token estimation, deterministic packing, `k` calls, the merge call |
| `src/mmlsa/pipeline/rewrite.py` | Step 3: cleaning, the four validation checks, batched retries, failure accounting |
| `tests/fixtures/mini_corpus/` | Three short locally authored texts driving `configs/mini.yaml` |
| `src/mmlsa/pipeline/orchestrator.py` | The `M`-run loop, run directory lifecycle, dry-run planner |
| `src/mmlsa/pipeline/noise.py` | Deterministic per-run selection of one foreign creation |
| `tests/integration/test_pipeline_end_to_end.py` | All six steps over the mini corpus, no provider |
| `tests/integration/test_orchestrator.py` | The whole run through the real configuration path |
| `data/function_words/en_core_v1.txt` | The versioned 127-entry list |

## Next actions

In order. Keep this list short; three to five items.

1. **Get a Gemini API key into `.env`, then `pip install -e ".[gemini]"`.** This is the only thing
   standing between the project and its first real measurement, and the one item here that cannot be
   done by writing code. Free tier is enough for M9.
2. **Finish M9**: one profile call and ten rewrite calls against each candidate model, then read the
   rewrites by hand. `docs/TESTING.md` section 7 lists what to look for — in particular whether the
   model is quietly modernizing spelling, which would inflate every delta uniformly and could look
   like a working method while measuring nothing.
3. **Before M10, settle Q10** (wh-adverbs in the function-word list). Changing that list changes
   every delta ever computed, so it has to be decided before any run of record.
4. **Run `--dry-run` before anything wide.** The planner's call count is exact, asserted by test, and
   it now plans against the configured model's real context window.
5. **Ask the supervisors Q10, Q12 and Q14** (see below). Q10 in particular has to be settled before
   any run of record.

## Blocked / waiting on

| Item | Waiting on | Since |
|---|---|---|
| Supervisor confirmation of the profile merge call | next meeting; `docs/OPEN_QUESTIONS.md` Q1 | 2026-08-15 |
| **Whether the function-word list should gain wh-adverbs** | next meeting; `docs/OPEN_QUESTIONS.md` Q10. Settle this **before** M10: changing the list changes every delta ever computed | 2026-08-15 |
| **The exact Gutenberg editions the reference paper used** | next meeting; `docs/OPEN_QUESTIONS.md` Q12. The supervisors are the paper's authors, so this is a five-minute question that removes a permanent caveat from the agreement report | 2026-08-15 |
| **`temperature = 0` cannot be sent to several current models** | next meeting; `docs/OPEN_QUESTIONS.md` Q14. The specification pins it and those models reject the parameter with a 400. Implemented as: send it where accepted, record its absence where not | 2026-08-16 |

## Environment

Facts that are easy to lose between sessions.

| | |
|---|---|
| Repository | `.../Desktop/Study/sem7/proj/Multi-Modal-LLM-Style-Analysis` |
| Remote | `https://github.com/eliranmeleh/Multi-Modal-LLM-Style-Analysis` |
| Python | 3.11.15, provisioned by `uv` into `.venv`. The system Python is 3.12 and is **not** used |
| Setup | `uv venv --python 3.11 .venv` then `uv pip install --python .venv -e ".[dev]"` |
| Run anything | `.venv/Scripts/python.exe -m mmlsa --help` (Windows) |
| Quality gate | `MMLSA_ALLOW_LIVE=0 pytest -q && ruff check . && ruff format --check . && mypy src` |

**Set `MMLSA_ALLOW_LIVE=0` when running the gate.** CI sets it on every run and a developer's shell
usually does not, so the suite exercises a different environment locally than it does on CI. That gap
hid a real bug for four pushes; see `docs/SESSION_LOG.md` 2026-08-16 (eighth).
| Secrets | `.env`, git-ignored, created from `.env.example`. Loaded from the **working directory** by every `mmlsa` command; an exported variable wins over the file |
| Provider SDKs | optional extras: `pip install -e ".[gemini]"`, `".[openai]"`, `".[anthropic]"`. None is needed to run the offline pipeline |

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
