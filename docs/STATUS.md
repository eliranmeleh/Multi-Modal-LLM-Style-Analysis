# STATUS

**The live board. Read this first in every session; update it before ending one.**

This file answers three questions and nothing else: where we are, what is next, what is blocked.
History belongs in `docs/SESSION_LOG.md`, not here. Findings belong in `docs/RESULTS.md`.

---

## At a glance

| | |
|---|---|
| **Last updated** | 2026-11-26 |
| **Phase** | B — implementation |
| **Current milestone** | M10 — Stage 1, proof of concept. **A pilot on 2026-11-24 failed its prediction, because the style profile described only the first play in its input** (`RESULTS.md` F-15). **Waits for the supervisors' answers** (Q18, Q10, Q15, agenda items J and B). The em dash question is settled (I34, #19). The profile check (I37, #29) is on `main`, so a run whose profile describes one creation now stops before Step 3. The Colab notebook asked for at meeting 1 is ready for the next meeting; its Part 6 runs M10 on the paid key, and a re-run in a new Colab session was verified to cost nothing (F-14) |
| **Pipeline state** | **The pipeline is finished and it has now run against a real provider.** All six steps, `M` times, with noise injection, into an immutable run directory. On 2026-08-29 it made its first live calls and produced real deltas on real text. **It runs in Google Colab** through `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb` (I30). |
| **Quality gates** | `ruff check`, `ruff format --check`, `mypy src` all clean; **705 tests pass** on Python 3.11 (`main` at `757d9c6`, after #19, #22, #24, #27, #29 and #25, 2026-11-26); 744 on #32; 782 on the M14 branch (#34), 805 on the M11 branch, with the 4 replay tests of `tests/validation` skipped until a check is recorded; CI runs the same on 3.13 |
| **CI** | **green at `757d9c6`** (`main` after #25, checked 2026-11-26). The check job runs on Python 3.11 and 3.13 |
| **Corpus** | 49 creations, 1,065,092 words, `corpus verify` passes 70 checks |
| **LLM provider** | `gemini`, `openai` and `anthropic` implemented and registered, each behind its own optional extra. **Proposed model of record `gemini-3.1-flash-lite`** (agenda item B). `gemini-3.5-flash`, chosen in I28 and still the provider default in `gemini.py`, **no longer exists** (`RESULTS.md` F-13), so every live command must name its model until the default changes. Swapping is one config key |
| **API key present** | **yes**, Gemini, project `mmlsa-phase-b`: in `.env` on the first computer and in Colab Secrets as `GEMINI_API_KEY`; none on the second computer. **Billing is set up since 2026-11-24**: paid Tier 1, prepay with auto-reload off, so the key stops rather than charging when the balance runs out. Google Cloud credit claimed on the billing account covers the measured cost of the remaining project |
| **Quota** | **paid Tier 1** since 2026-11-24, about 4,000 requests a minute and 4 million input tokens a minute for `gemini-3.1-flash-lite` (F-13). The free-tier figures it replaces are in F-12 and F-13. `configs/default.yaml` still asks for 4 per minute at concurrency 1; the notebook's `TIER = "paid"` raises that to 240 and 8. The offline backends are not throttled at all (`DECISIONS.md` I29) |
| **Blocked on** | **the supervisors' answers**, above all Q18 (how Step 1 is run, so that the profile describes the whole corpus) and Q10 (the function-word list), which must be settled before any run of record. **No meeting is scheduled yet.** Billing is no longer a blocker. Measured cost of the whole remaining project: **37 to 47 dollars on `gemini-3.1-flash-lite`**, M10 alone 1.43 (`RESULTS.md` F-13, which supersedes the review's 43 to 65) |

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
| M11 | Stage 2, reproducibility and sensitivity | **code built, not run**: `experiment sensitivity` runs one run per `P`, then writes the stability, `P`-sweep and `M` tables and a verdict; tested on `configs/mini.yaml`. Waits for M10 and Q22 |
| M12 | Stage 3, full corpus run | not started |
| M13 | Stage 5, control experiment | **code built, not run** (#31, #32): `python -m mmlsa experiment control` runs end to end on `configs/mini.yaml` with the fake provider. Done only after a real run, which waits for Q18 and Q20 |
| M14 | Validation test suite | **code built, not recorded** (#34): `experiment calibration`, `mixture`, `heldout` and `noise` run end to end on `configs/mini.yaml` with the fake provider, against a finished baseline run; `pytest tests/validation -q` replays recorded bundles and skips until one exists. Done only after the bundles are recorded from the run of record, which waits for M12 and Q21 |
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
| `src/mmlsa/experiments/control.py` | M13: a stratified sample rewritten under the profile (Mode A) and under the generic prompt (Mode B); paired t-test, confidence interval, `d_z`, Wilcoxon, achieved power; `control.json`, `pairs.csv`, both arms' rewrites, `summary.md` (I38) |
| `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb` | The pipeline in Google Colab: install, the whole method offline on `configs/mini.yaml`, then a live `compare` on Macbeth and Henry VIII with each step's output, then the same command again from the cache; Part 6 runs `configs/poc.yaml` (M10) behind a dry run, a cost estimate and `RUN_POC`; Part 7 times the cache on Drive. A free or paid `TIER` sets the request limits of every live command, and each live part prints its tokens and cost. Asked for at meeting 1; not a `docs/PLAN.md` milestone |

## Next actions

In order. Keep this list short; three to five items.

0. **Schedule the next meeting, show the Colab notebook and the pilot (F-15)**, and settle agenda
   items A to L in `docs/MEETINGS.md`. Record each answer in `docs/DECISIONS.md` the same day.
1. **Settle Q18 before M10.** The pilot's profile described A Yorkshire Tragedy alone, so its scores
   test nothing. The proposal is smaller extraction bins, so the specified merge call keeps only what
   the plays share; it changes `k`, so it needs the supervisors' word. Rerunning the pilot that way
   costs about $1.40.
2. **#21 has only #33 left.** `MyDrive/mmlsa` has its `SHARED_FOLDER.txt`, and its `cache` now holds
   the pilot's 1,005 answers beside the 26 from Colab, 1,031 in all (copied 2026-11-26). Until #9
   changes the default model, a command reuses them only with
   `--set llm.model_id=gemini-3.1-flash-lite`. #33 adds the hint for a first Drive mount that fails;
   #21 closes with it.
3. **Use the paid tier.** Billing has been on since 2026-11-24. For local runs, raise
   `llm.requests_per_minute` and `llm.concurrency` in `configs/default.yaml` (240 and 8 are
   reasonable) and re-run `--dry-run` before anything wide. No code changes. In Colab, set
   `TIER = "paid"` in Part 1, which does the same for the notebook's commands.
   Before M10 in Colab, run the notebook's Part 7 once (review N5): if Drive is slow with many small
   files, set `CACHE_ON_DRIVE = False`. Always allow the Drive prompt: without it the answers stay on
   the runtime disk and are paid for again next session (F-14).
4. **Settle Q10 before M10** (wh-adverbs in the function-word list). Unchanged and still true:
   changing that list changes every delta ever computed, so it must be decided before any run of
   record. The em dash, the other such change, was settled in I34 and merged on 2026-11-26.
5. **Then M10**, and run `--dry-run` first. Check the profile before trusting the scores (F-15).
6. **Review and merge #32, the control experiment's code (M13).** Merge after #30, which it builds
   on. Once Q18 and Q20 are settled and M10 has run, `experiment control --config
   configs/control.yaml` prints its plan (one profile over the corpus, 600 rewrites) before `--yes`.
7. **Review and merge the M14 checks (#34)** after #32, which they build on. Add Q21 (the numbers
   behind the pass conditions) to the meeting. After the run of record, run each check with
   `--baseline <run id>` and record its bundle as `docs/RUNBOOK.md` says.
8. **Review and merge #37 (replay with no key) and the M11 sweep.** #37 is from `main`; the sweep
   builds on #35. Add Q22 to the meeting.

## Blocked / waiting on

| Item | Waiting on | Since |
|---|---|---|
| Supervisor confirmation of the profile merge call | next meeting; `docs/OPEN_QUESTIONS.md` Q1 | 2026-08-15 |
| **Whether the function-word list should gain wh-adverbs** | next meeting; `docs/OPEN_QUESTIONS.md` Q10. Settle this **before** M10: changing the list changes every delta ever computed | 2026-08-15 |
| **The exact Gutenberg editions the reference paper used** | next meeting; `docs/OPEN_QUESTIONS.md` Q12. The supervisors are the paper's authors, so this is a five-minute question that removes a permanent caveat from the agreement report | 2026-08-15 |
| **`temperature = 0` cannot be sent to several current models** | next meeting; `docs/OPEN_QUESTIONS.md` Q14. **Partly answered 2026-08-29:** every reachable Gemini model accepts it, so the configuration of record does transmit the specified value | 2026-08-16 |
| **Whether the extraction prompt should require a single unified profile** | next meeting; `docs/OPEN_QUESTIONS.md` Q15. `docs/PROMPTS.md` is frozen, so this needs their word rather than an edit | 2026-08-29 |
| ~~Billing on the API project~~ | **done 2026-11-24**: Tier 1, prepay, auto-reload off. What the college reimburses is still agenda item C | 2026-08-29 |
| **How Step 1 is run, so that the profile describes the whole corpus** | next meeting; `docs/OPEN_QUESTIONS.md` Q18, agenda item J. Blocks M10: the pilot's profile described one play (F-15) | 2026-11-26 |
| **Whether the noise step raises every delta** | next meeting; `docs/OPEN_QUESTIONS.md` Q19, agenda item K. In the pilot, run 1 without noise scored about half of runs 2 and 3 (F-15) | 2026-11-26 |
| **The supervisors' answers to agenda items A to K** | next meeting, **not yet scheduled**; `docs/MEETINGS.md` | 2026-11-21 |

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
