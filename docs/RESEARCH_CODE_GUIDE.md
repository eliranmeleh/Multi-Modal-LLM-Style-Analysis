# Appendix 2 — Research Code Guide

*Capstone Project Phase B, project 26-2-R-6: Multi-Modal LLM Style Analysis.*

This guide is for whoever continues the research or reuses the code: to extend an experiment, change
its parameters, run it on another author, or swap in another model or distance. It describes the
structure of the code, its dependencies, and the exact places to change for each kind of extension.
Installation is in Appendix 1, section 2.

---

## 1. The method in one paragraph

A language model reads the corpus and writes a **style profile** of its dominant author (Step 1).
Every text is cut into chunks of `P` words (Step 2). The model rewrites each chunk to match the
profile (Step 3). The **style distance** between a chunk and its rewrite, the Function-Word Edit
Distance (FWED: the edit distance between the two sequences of function words, divided by the
longer length), measures how much the model had to change (Step 4). A text's score is the mean over
its chunks, then the mean over `M` independent runs (Step 5). Otsu's method splits the scores into
two groups at a threshold `tau`: texts below it read as authentic, texts above it as suspicious
(Step 6). Runs 2 to `M` each add one foreign text to the profiling corpus ("noise injection"), so
the profile describes the corpus's shared style rather than any single text.

Steps 2, 4, 5 and 6 contain no model calls. They are pure functions, unit-tested with exact
expected values, and they are what makes a recorded run replay byte for byte.

## 2. Dependencies

Python 3.11 to 3.13. Declared in `pyproject.toml`; `pip install -e ".[dev]"` installs all of them.

| Package | Used for |
|---|---|
| `typer` | the command-line interface, `python -m mmlsa ...` |
| `pydantic`, `pydantic-settings`, `pyyaml` | the validated configuration |
| `python-dotenv` | reading API keys from `.env` |
| `numpy`, `pandas`, `scipy` | aggregation, statistics (paired t-test, Wilcoxon) |
| `python-Levenshtein` | the edit distance inside FWED |
| `scikit-image`, `scikit-learn` | Otsu cross-check; the two-component Gaussian mixture fallback |
| `matplotlib`, `seaborn` | the figures |
| `tqdm`, `structlog` | progress bars, structured JSON logs |
| `tenacity` | retry with backoff for transient provider errors |

Optional, one per model provider: `google-genai` (`.[gemini]`), `openai` (`.[openai]`),
`anthropic` (`.[anthropic]`). Development only (`.[dev]`): `pytest`, `pytest-cov`, `hypothesis`,
`ruff`, `mypy` and type stubs.

## 3. Repository layout

```
configs/          one YAML file per experiment; all inherit from default.yaml
data/             the corpus and every other input (texts, function words, judged cases)
src/mmlsa/        the package
tests/            unit, integration, contract, data and validation tests
notebooks/        the Google Colab notebook
docs/             specification, design decisions, results, these guides
runs/             one immutable directory per run (created by the program)
cache/            every model answer, by request hash (created by the program)
reports/          the final report of a run (created by `report`)
release/          release archives (created by `release`, never committed)
```

### 3.1 The package, `src/mmlsa/`

| Module | Role |
|---|---|
| `cli.py` | every command; the only module that prints |
| `config.py`, `settings.py` | the configuration model (Pydantic), file inheritance, `--set` overrides, the configuration hash |
| `corpus/` | `gutenberg.py` downloads and strips Project Gutenberg texts; `normalize.py` removes editorial matter only and keeps the original spelling, which is the signal; `loader.py` reads the source declaration and loads texts; `manifest.py` checksums |
| `chunking.py` | **Step 2**: `P`-word chunks with full coverage |
| `pipeline/profile.py` | **Step 1**: packs the corpus into as few calls as the model's context allows, then merges the partial profiles |
| `pipeline/profile_sources.py` | checks the profile does not describe a single text |
| `pipeline/rewrite.py` | **Step 3**: rewrites, validates each answer (length, content kept, refusals), retries |
| `distance/` | **Step 4**: `tokenize.py`, `fwed.py`, and `registry.py` for selecting a metric |
| `pipeline/score.py` | **Step 5**: mean over chunks, then over runs; failure accounting |
| `pipeline/classify.py` | **Step 6**: exact Otsu, `skimage` cross-check, Gaussian mixture, manual; bimodality diagnostics |
| `pipeline/noise.py` | the seeded choice of a foreign text for each run |
| `pipeline/orchestrator.py` | runs Steps 1 to 6 `M` times into a run directory; resume; dry-run planning |
| `pipeline/compare.py` | compares candidate models on identical chunks |
| `llm/base.py` | the `LLMProvider` protocol, `LLMRequest`, `LLMResponse` |
| `llm/cache.py` | the content-addressed answer store, `cache/<key[:2]>/<key>.json` |
| `llm/ledger.py` | `calls.jsonl`: every request and response |
| `llm/runner.py` | concurrency, rate limit, retries; every call goes through the cache and the ledger |
| `llm/providers/` | `gemini.py`, `openai.py`, `anthropic.py` (live); `fake.py` (deterministic, offline); `replay.py` (cache only) |
| `prompts/` | the prompt templates as text files, and `versions.json` |
| `experiments/` | `control.py` (profile vs generic prompt), `validation.py` (the four checks), `sensitivity.py` (stability across runs and `P`) |
| `reporting/` | `tables.py`, `plots.py` (run outputs); `report.py` (the final report); `release.py` (release and reproduce) |
| `utils/` | hashing, logging, text helpers, token estimates |

### 3.2 How a run flows

```
configs/full.yaml ──► Config ──► orchestrator.execute_run
                                    for run i in 1..M:
                                      corpus (+ one noise text if i > 1)
                                        ├─ Step 1 profile.extract_profile ──► Runner ──► cache / provider
                                        ├─ Step 2 chunking.chunk_text
                                        ├─ Step 3 rewrite.rewrite_chunks  ──► Runner ──► cache / provider
                                        └─ Step 4 distance(original, rewrite) per chunk
                                    Step 5 score.aggregate_run, aggregate_creation  (mean over chunks, then runs)
                                    Step 6 classify.classify    (tau, labels)
                                    write runs/<run_id>/  (scores.csv, threshold.json, figures, ...)
```

Every model call is an `LLMRequest`. The `Runner` hashes it into a cache key; a stored answer is
returned without a call, and every call, cached or not, is appended to the ledger. That is why any
run can be replayed, resumed, or re-run for free.

### 3.3 Configuration

One YAML file per experiment under `configs/`. Each names a parent with `extends:` and overrides
only what differs; `default.yaml` holds every key with a comment. Precedence: command-line flags,
then environment, then the file, then defaults. Any key can be overridden for one command with
`--set key=value`. The resolved configuration is hashed into the run id and saved as
`config.snapshot.yaml` in the run directory, so a run always records exactly what produced it.

## 4. Rules that keep results valid

Keep these when extending the code. Each is enforced by a test.

1. **No author or corpus name in `src/`.** The author's name lives only in `data/` and `configs/`
   (`corpus.author_label`). `tests/test_no_hardcoded_author.py` fails otherwise. This is what lets
   the method run on another author unchanged.
2. **Every model call goes through `Runner`.** Never call a provider directly: the cache and the
   ledger are what make results traceable and reproducible.
3. **Run directories are never overwritten.** New parameters mean a new run id.
4. **Randomness uses the run seed** (`run.seed`): sampling, noise choice, splice positions.
5. **Tests never call a real model.** They use `FakeProvider` or `ReplayProvider`; the test
   environment blocks live providers (`MMLSA_ALLOW_LIVE=0`).
6. **The function-word list and the prompts are versioned, never edited in place** (sections 5.5
   and 5.6), because changing either changes every distance ever measured.

## 5. Extending the experiment

### 5.1 Change parameters

For one run, override on the command line:

```bash
python -m mmlsa run --config configs/full.yaml --set chunking.P=300 --set run.M=5
python -m mmlsa run --config configs/full.yaml --set noise.enabled=false
python -m mmlsa run --config configs/full.yaml --set classify.method=gmm_2
```

For a lasting experiment, add a file under `configs/` that extends an existing one:

```yaml
# configs/p300.yaml
extends: full.yaml
chunking:
  P: 300
```

The parameters most worth varying, all in `configs/default.yaml`:

| Key | Meaning | Default |
|---|---|---|
| `chunking.P` | chunk length in words | 400 |
| `run.M` | independent runs averaged | 3 |
| `run.seed` | seed for every random choice | 20260731 |
| `noise.enabled` | inject one foreign text in runs 2 to `M` | true |
| `llm.provider`, `llm.model_id`, `llm.temperature` | the model | gemini, provider default, 0.0 |
| `distance.metric`, `distance.function_words` | the style distance and its word list | fwed, `en_core_v1.txt` |
| `classify.method` | `otsu_exact`, `otsu_skimage`, `gmm_2` or `manual` (with `classify.manual_tau`) | otsu_exact |
| `classify.borderline_band` | scores this close to `tau` are reported as borderline | 0.01 |
| `rewrite.validation.*` | when a rewrite is rejected and retried | see file |
| `corpus.include_ids`, `corpus.exclude_ids` | run on a subset | whole corpus |

Before any run that calls a model, `--dry-run` prints the number of calls and tokens and sends
nothing. Changing `P`, the model, the prompts or the corpus changes the requests, so those answers
are not in the cache and are paid for; changing anything in Steps 4 to 6 does not change a request.

### 5.2 Run it on another author or another corpus

No code changes. Use the development corpus as the template: `tests/fixtures/mini_sources.yaml`,
`tests/fixtures/mini_corpus/` and `configs/mini.yaml`.

1. **Declare the texts** in a new sources file, for example `data/marlowe/sources.yaml`, with
   `author_label` and four lists: `texts` (the corpus under study), `noise_pool` (foreign texts for
   injection), `heldout` and `mixture_sources` (for the validation checks). Each entry has an `id`,
   a `title`, a `gutenberg_id` (or `null` for a text you supply yourself) and optionally
   `expected_words`. The four lists must not share a text; the loader checks this.
2. **Provide the texts.** For Project Gutenberg texts, `python -m mmlsa corpus fetch --config <yours>`
   downloads, strips and normalizes them. Otherwise place each normalized text as `<id>.txt` in the
   corpus directory (UTF-8, one file per text).
3. **Write a configuration** that points at them:

   ```yaml
   # configs/marlowe.yaml
   extends: default.yaml
   corpus:
     author_label: "Marlowe"
     dir: "data/marlowe/corpus"
     sources: "data/marlowe/sources.yaml"
     manifest: "data/marlowe/manifest.json"
     expected_count: 7
   noise:
     pool_dir: "data/marlowe/noise_pool"
   experiment:
     heldout: {dir: "data/marlowe/heldout"}
     mixture: {dir: "data/marlowe/mixture_sources"}
     sensitivity: {exempt: []}
   report:
     consensus_cases: "data/marlowe/consensus_cases.yaml"
     compare_to_prior: "data/marlowe/prior_findings.yaml"
   ```

4. **Another language** needs its own function-word list (`distance.function_words`), one word per
   line, following the format of `data/function_words/en_core_v1.txt`.
5. **Judging the result** is optional: `consensus_cases.yaml` lists texts with a known expected
   label, and `prior_findings.yaml` a previous study's flagged set, in the format of the files in
   `data/`. They are read by `report` only, never by the method.
6. Check, then plan. For texts fetched from Project Gutenberg, `corpus fetch` writes a manifest
   of checksums and `python -m mmlsa corpus verify --config configs/marlowe.yaml` checks the texts
   against it. Texts you supply yourself have no manifest, so skip that step: the run itself loads
   every declared text and stops on a missing one. Then
   `python -m mmlsa run --config configs/marlowe.yaml --dry-run`, and first try the method with
   `--provider fake`, which needs no key.

### 5.3 Use another model

The three live providers are interchangeable by configuration:

```bash
pip install -e ".[openai]"            # and OPENAI_API_KEY in .env
python -m mmlsa run --config configs/poc.yaml --provider openai --set llm.model_id=<model> --dry-run
```

To compare models before choosing, `python -m mmlsa compare --config configs/poc.yaml -m gemini:<model>
-m openai:<model>` rewrites the same chunks with each and writes a side-by-side summary.

To add a new provider:

1. Write `src/mmlsa/llm/providers/<name>.py` with a class that satisfies the `LLMProvider` protocol
   in `llm/base.py`: the attributes `name`, `model_id` and `sends_requests`, and the methods
   `context_window()` and `complete(request) -> LLMResponse`. The shared helpers in
   `llm/providers/_live.py` (key from the environment, optional SDK loading, error classification)
   do most of the work; `gemini.py` is the reference implementation.
2. Register it in `_REGISTRY` in `src/mmlsa/llm/providers/__init__.py`, and add it to `LIVE`.
3. Add its SDK as an optional extra in `pyproject.toml`.
4. Add it to `tests/contract/test_live_providers.py`, which tests every provider against a stub SDK.

Nothing under `pipeline/` changes.

### 5.4 Add a style distance

1. Write a class in `src/mmlsa/distance/` with a `name` and a `__call__(original, rewrite)` that
   returns a `DistanceResult` with a value in [0, 1] (protocol `StyleDistance` in `distance/base.py`;
   `fwed.py` is the reference).
2. Register it in `_REGISTRY` in `src/mmlsa/distance/registry.py`.
3. Select it with `--set distance.metric=<name>`.

A distance is computed from text the model has already written, so a new one changes no request:
re-running an existing configuration with another metric reads every rewrite from the cache and
costs nothing. This makes metrics directly comparable on identical rewrites.

### 5.5 Change the function-word list

Never edit `data/function_words/en_core_v1.txt` in place. Copy it to a new version
(`en_core_v2.txt`), make the change there, and select it with `distance.function_words`. Earlier
runs stay valid and comparable, because each run records which list it used.

### 5.6 Change a prompt

The templates are the `.txt` files in `src/mmlsa/prompts/`. After editing one, increase its number
in `prompts/versions.json`. The version is part of every request's cache key, so exactly the
answers produced by the old template stop being reused, and nothing else.

### 5.7 Add an experiment

The three experiments in `src/mmlsa/experiments/` follow one pattern, and a new one should too:

1. A module with a planning function that counts calls without making any (`plan_control`,
   `plan_sweep`, `plan_check`), and a `run_<name>(config, ...)` that makes its calls through `Runner`, writes its own immutable
   directory under `runs/` (a `manifest.json` with `experiment`, `ended_utc` and `verdict`, its
   result as `<name>.json`, a `summary.md`, and its ledger), and returns a result object.
2. A command in `cli.py` under `experiment_app` that prints the plan and stops unless `--yes`.
3. Tests with the mini configuration and the fake provider, like
   `tests/integration/test_validation_checks.py`.

`report --include <run id>` then lists the new experiment's verdict in the final report.

## 6. Testing

```bash
MMLSA_ALLOW_LIVE=0 pytest -q                     # the whole suite, offline, a few minutes
pytest tests/unit -q                              # the deterministic core only
ruff check . && ruff format --check . && mypy src
```

| Folder | What it tests |
|---|---|
| `tests/unit/` | each deterministic step against exact expected values (chunking, tokenizer, FWED, aggregation, Otsu, cache, configuration) |
| `tests/integration/` | whole runs and experiments on the three-text mini corpus with the fake provider; release and reproduce |
| `tests/contract/` | every provider against the protocol (`test_provider_contract.py`), and the live ones against stub SDKs (`test_live_providers.py`) |
| `tests/data/` | corpus integrity and that the four text sets are disjoint |
| `tests/validation/` | replays recorded runs of the four validation checks and asserts their verdicts |

The fake provider answers deterministically from a hash of the prompt, so integration tests check
behaviour and structure, never the scientific result. The scientific results are checked by
`tests/validation/` on recorded real runs, and by Appendix 1's `reproduce`.

## 7. Further documentation

| Question | File |
|---|---|
| What exactly does the method do? | `docs/SPEC.md` |
| How is the code organised, in detail? | `docs/ARCHITECTURE.md` |
| Where does the corpus come from? | `docs/DATA.md`, `data/corpus_sources.yaml` |
| The exact prompt texts | `docs/PROMPTS.md` |
| The experiments and their pass conditions | `docs/EXPERIMENTS.md`, `docs/TESTING.md` |
| Why was each design choice made? | `docs/DECISIONS.md` |
| What is still open? | `docs/OPEN_QUESTIONS.md` |
| Running, monitoring and recovering long jobs | `docs/RUNBOOK.md` |
| Which code implements which requirement | `docs/TRACEABILITY.md` |
| Terms and symbols | `docs/GLOSSARY.md` |
