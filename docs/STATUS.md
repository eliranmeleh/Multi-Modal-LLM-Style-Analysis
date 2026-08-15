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
| **Current milestone** | M2 — corpus acquisition |
| **Pipeline state** | the whole deterministic core is built and tested: chunking, FWED, aggregation, thresholding, result artifacts. No LLM code yet, by design. |
| **Quality gates** | `ruff check`, `ruff format --check`, `mypy src` all clean; 227 tests pass; 91 percent coverage |
| **LLM provider** | none wired yet. Plan: Gemini free tier first (`llm.provider: gemini`), swap later by one config key |
| **API key present** | no. Not needed before M9 |
| **Blocked on** | nothing |

## Milestone board

Mirrors `docs/PLAN.md`. That file holds the acceptance criteria; this is the glance view.

| | Milestone | State |
|---|---|---|
| M0 | Repository skeleton | **done** (CI green pending first push) |
| M1 | Config and logging | **done** |
| M2 | Corpus acquisition and normalization | next |
| M3 | Chunking, tokenizer and FWED | **done except** the two corpus-wide properties, which need M2 |
| M4 | Aggregation and exact Otsu | **done** |
| M5 | Provider protocol, cache, ledger, runner | not started |
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

Everything through M4 is offline and needs no API key. That is deliberate: see `docs/PLAN.md`,
ordering principle. The pipeline can already score, threshold, classify and plot — it just has
nothing to score yet.

## What exists now

| Path | What it does |
|---|---|
| `src/mmlsa/config.py`, `settings.py` | Pydantic model, `extends` resolution, config hashing, four-layer precedence |
| `src/mmlsa/chunking.py` | Step 2, full coverage, trailing chunk kept |
| `src/mmlsa/distance/` | Step 4: tokenizer, FWED, registry |
| `src/mmlsa/pipeline/score.py` | Step 5, mean over chunks then over runs, failure accounting |
| `src/mmlsa/pipeline/classify.py` | Step 6, exact Otsu, skimage cross-check, GMM fallback, bimodality diagnostics |
| `src/mmlsa/reporting/` | `scores.csv`, `threshold.json`, sorted scatter, histogram, run variance |
| `data/function_words/en_core_v1.txt` | The versioned 127-entry list |

## Next actions

In order. Keep this list short; three to five items.

1. **M2, and budget real time for it.** Extract the 49 titles and Gutenberg identifiers from
   `fqaf009.pdf` into `data/corpus_sources.yaml`; then fetch, strip boilerplate, normalize, build
   the manifest. Text acquisition is where silent errors enter.
2. **Close out M3** by re-running the full-coverage round trip and `delta(x, x) == 0` over the real
   corpus, then mark the milestone done.
3. **M5**, the provider protocol, cache and ledger. This is the load-bearing piece of the
   architecture; read `docs/ARCHITECTURE.md` section 4 before writing any of it.
4. Get a Gemini API key so M9 is not blocked when it arrives.

## Blocked / waiting on

| Item | Waiting on | Since |
|---|---|---|
| Supervisor confirmation of the profile merge call | next meeting; `docs/OPEN_QUESTIONS.md` Q1 | 2026-08-15 |
| **Whether the function-word list should gain wh-adverbs** | next meeting; `docs/OPEN_QUESTIONS.md` Q10. Settle this **before** M10: changing the list changes every delta ever computed | 2026-08-15 |

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
