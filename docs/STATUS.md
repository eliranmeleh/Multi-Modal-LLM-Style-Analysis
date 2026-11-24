# STATUS

**The live board. Read this first in every session; update it before ending one.**

This file answers three questions and nothing else: where we are, what is next, what is blocked.
History belongs in `docs/SESSION_LOG.md`, not here. Findings belong in `docs/RESULTS.md`.

---

## At a glance

| | |
|---|---|
| **Last updated** | 2026-11-24 |
| **Phase** | B — implementation |
| **Current milestone** | M10 — Stage 1, proof of concept. **Needs a billing decision first.** The Colab notebook asked for at meeting 1 is ready for the next meeting, and since 2026-11-24 it has a part that runs M10 once a paid key is in place |
| **Pipeline state** | **The pipeline is finished and it has now run against a real provider.** All six steps, `M` times, with noise injection, into an immutable run directory. On 2026-08-29 it made its first live calls and produced real deltas on real text. **It runs in Google Colab** through `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb` (I30). |
| **Quality gates** | `ruff check`, `ruff format --check`, `mypy src` all clean; **617 tests pass** on Python 3.11 (numpy 2.4.6, pandas 3.1.1) and 3.13 (numpy 2.5.5, pandas 3.1.1) |
| **CI** | **green at `4df8129`** (`main`, checked 2026-11-24). The check job runs on Python 3.11 and 3.13 |
| **Corpus** | 49 creations, 1,065,092 words, `corpus verify` passes 70 checks |
| **LLM provider** | `gemini`, `openai` and `anthropic` implemented and registered, each behind its own optional extra. **Proposed model of record `gemini-3.1-flash-lite`** (agenda item B). `gemini-3.5-flash`, chosen in I28 and still the provider default in `gemini.py`, **no longer exists** (`RESULTS.md` F-13), so every live command must name its model until the default changes. Swapping is one config key |
| **API key present** | **yes**, Gemini free tier, project `mmlsa-phase-b`: in `.env` on the first computer and in Colab Secrets as `GEMINI_API_KEY`; none on the second computer. **No billing is set up on the project.** The team's Google AI Pro subscription includes 10 dollars a month of Google Cloud credit that the API can use once billing is on and the credit is claimed in AI Studio (F-13) |
| **Quota** | free tier, read from AI Studio on 2026-11-24 (F-13): **`gemini-3.1-flash-lite` and `gemini-3.5-flash-lite` allow 15 requests a minute and 500 a day**, every other text model 5 a minute and 20 a day; **250,000 input tokens per minute per model** (F-12). `configs/default.yaml` asks for 4 per minute at concurrency 1. The offline backends are not throttled at all (`DECISIONS.md` I29) |
| **Blocked on** | **billing on the API project, which is planned but not yet in place** (decided 2026-08-29). At 500 a day M10 (972 calls) fits the free tier in two days, but the whole project (27,000 to 35,000 calls) would take 54 to 70 days, and the full corpus's profile requests of about 560,000 tokens cannot pass the free tier's per-minute token limit at all. Measured cost of the whole remaining project: **37 to 47 dollars on `gemini-3.1-flash-lite`**, M10 alone 1.43 (`RESULTS.md` F-13, which supersedes the review's 43 to 65). Nothing in the code changes when it arrives: raise `llm.requests_per_minute` and `llm.concurrency` in `configs/default.yaml` |

## Milestone board

Mirrors `docs/PLAN.md`. That file holds the acceptance criteria; this is the glance view.

| | Milestone | State |
|---|---|---|
| M0 | Repository skeleton | **done.** CI is green as of `0659e98` — the first green run in the project's history; every push from M5 to M9 was red for a single cause, see the session log for 2026-08-16 |
| M1 | Config and logging | **done** |
| M2 | Corpus acquisition and normalization | **done** |
| M3 | Chunking, tokenizer and FWED | **done**, including the corpus-wide properties |
| M4 | Aggregation and exact Otsu | **done** |
| M5 | Provider protocol, cache, ledger, runner | **done** |
| M6 | Step 1, profile extraction | **done** |
| M7 | Step 3, rewriting | **done** |
| M8 | Orchestrator, `M` runs, noise injection | **done** |
| M9 | First real call, provider comparison | **done, 2026-08-29.** Two models compared on ten identical chunks; `summary.md` in `runs/compare-20260829T1247-s20260731` is the artifact. `RESULTS.md` F-09, F-10, F-11. One provider only, which F-11 states as a limit |
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
| `src/mmlsa/pipeline/compare.py` | M9's harness: every candidate rewrites the same chunks; writes `summary.md`, `comparison.csv`, side-by-side `rewrites/`, `profiles/` and `calls.jsonl` |
| `src/mmlsa/prompts/` | The book's prompt templates verbatim, versioned; rendering and profile serialization |
| `src/mmlsa/pipeline/profile.py` | Step 1: token estimation, deterministic packing, `k` calls, the merge call |
| `src/mmlsa/pipeline/rewrite.py` | Step 3: cleaning, the four validation checks, batched retries, failure accounting |
| `tests/fixtures/mini_corpus/` | Three short locally authored texts driving `configs/mini.yaml` |
| `src/mmlsa/pipeline/orchestrator.py` | The `M`-run loop, run directory lifecycle, dry-run planner |
| `src/mmlsa/pipeline/noise.py` | Deterministic per-run selection of one foreign creation |
| `tests/integration/test_pipeline_end_to_end.py` | All six steps over the mini corpus, no provider |
| `tests/integration/test_orchestrator.py` | The whole run through the real configuration path |
| `data/function_words/en_core_v1.txt` | The versioned 127-entry list |
| `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb` | The pipeline in Google Colab: install, the whole method offline on `configs/mini.yaml`, then a live `compare` on Macbeth and Henry VIII with each step's output, then the same command again from the cache; Part 6 runs `configs/poc.yaml` (M10) behind a dry run, a cost estimate and `RUN_POC`; Part 7 times the cache on Drive. A free or paid `TIER` sets the request limits of every live command, and each live part prints its tokens and cost. Asked for at meeting 1; not a `docs/PLAN.md` milestone |

## Next actions

In order. Keep this list short; three to five items.

0. **Show the Colab notebook at the next meeting** and settle agenda items A to I in
   `docs/MEETINGS.md`. Record each answer in `docs/DECISIONS.md` the same day.
1. **Set up billing on the API project.** Decided on 2026-08-29, not yet done; it is one button,
   *Set up billing*, on the project in Google AI Studio, and the same key then becomes a paid key.
   M10 can start before that, on the free tier's 500 a day; M11 onward cannot (F-13). Claim the
   Google AI Pro plan's 10 dollars a month of Cloud credit in AI Studio at the same time. Once billing is on, raise `llm.requests_per_minute` and `llm.concurrency` in `configs/default.yaml`
   (240 and 8 are reasonable) and re-run `--dry-run` before anything wide. No code changes. In Colab,
   `TIER = "paid"` in Part 1 does the same for the notebook's commands.
   Before M10 in Colab, run the notebook's Part 7 once (review N5): if Drive is slow with many small
   files, set `CACHE_ON_DRIVE = False`.
2. **Settle Q10 before M10** (wh-adverbs in the function-word list). Unchanged and still true:
   changing that list changes every delta ever computed, so it must be decided before any run of
   record.
3. **Put Q15 to the supervisors** — may one sentence be added to the extraction prompt requiring a
   single unified profile? It is cheap to answer and `docs/PROMPTS.md` is frozen without their word.
4. **Then M10**, and run `--dry-run` first. Remember the new arithmetic: on the free tier the plan's
   call count is also a duration in days divided by twenty.
5. **Before M11, put the run number into the cache key.** `LLMRequest.cache_fields` has no replicate
   index, so `M` runs on identical inputs (Stage 2a), the calibration check and the no-noise variant
   would get run 1's cached answers back, which is zero variance by construction.

## Blocked / waiting on

| Item | Waiting on | Since |
|---|---|---|
| Supervisor confirmation of the profile merge call | next meeting; `docs/OPEN_QUESTIONS.md` Q1 | 2026-08-15 |
| **Whether the function-word list should gain wh-adverbs** | next meeting; `docs/OPEN_QUESTIONS.md` Q10. Settle this **before** M10: changing the list changes every delta ever computed | 2026-08-15 |
| **The exact Gutenberg editions the reference paper used** | next meeting; `docs/OPEN_QUESTIONS.md` Q12. The supervisors are the paper's authors, so this is a five-minute question that removes a permanent caveat from the agreement report | 2026-08-15 |
| **`temperature = 0` cannot be sent to several current models** | next meeting; `docs/OPEN_QUESTIONS.md` Q14. **Partly answered 2026-08-29:** every reachable Gemini model accepts it, so the configuration of record does transmit the specified value | 2026-08-16 |
| **Whether the extraction prompt should require a single unified profile** | next meeting; `docs/OPEN_QUESTIONS.md` Q15. `docs/PROMPTS.md` is frozen, so this needs their word rather than an edit | 2026-08-29 |
| **Billing on the API project** | decided 2026-08-29, pending. M10 fits the free tier's 500 a day; M11 to M14 do not (F-13); see the Next actions. Meeting 1: the team pays later; what the college reimburses is agenda item C | 2026-08-29 |
| **The supervisors' answers to agenda items A to I** | next meeting; `docs/MEETINGS.md` | 2026-11-21 |

## Environment

Facts that are easy to lose between sessions.

| | |
|---|---|
| Repository | `.../Desktop/Study/sem7/proj/Multi-Modal-LLM-Style-Analysis` (inside OneDrive), and on a second computer `.../Desktop/renatazeev/Multi-Modal-LLM-Style-Analysis` (outside it) |
| Remote | `https://github.com/eliranmeleh/Multi-Modal-LLM-Style-Analysis` |
| Python | 3.11.15, provisioned by `uv` into `.venv`: the development baseline. 3.12 and 3.13 are supported too (I30) |
| Colab | `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb`, opened from the badge in `README.md`. Key in Colab Secrets as `GEMINI_API_KEY`; results in Google Drive under `MyDrive/mmlsa` |
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

*Python.* `uv` supplies 3.11 because the approved book's tools table names it. `requires-python` was
widened on purpose in I30, so that Colab can install the package; keep developing on 3.11, which CI
also checks. A version error locally still means the wrong interpreter: activate the venv.

## Conventions for keeping this file honest

- A milestone moves to **done** only when its acceptance criterion in `docs/PLAN.md` demonstrably
  passes, not when the code exists. M3 above is the worked example of saying so.
- If something is half-finished, say so here in one line rather than leaving it implied.
- Never record a measurement here. Measurements go to `docs/RESULTS.md` with the run id that produced
  them.
