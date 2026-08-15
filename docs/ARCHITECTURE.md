# ARCHITECTURE

How the code is organised, what the interfaces are, and where data lives.

---

## 1. Design forces

Five properties drive every structural decision below.

1. **The pipeline is expensive and long-running.** Roughly 7,500 LLM calls per full run. Anything that
   makes a crash cost a full restart is unacceptable. Hence: content-addressed caching and resumability.
2. **Reproducibility is a graded requirement.** A run must be repeatable exactly. Hence: pinned model
   versions, seeded randomness, immutable run directories, a call ledger, and a replay mode.
3. **The deterministic core must be testable without a provider.** Chunking, distance, aggregation and
   thresholding contain no LLM calls, so they are pure functions with exact expected values.
4. **The method is author-agnostic and metric-agnostic.** Both the distance and the classifier are
   swappable through registries, because Phase B compares alternatives.
5. **The repository is a public academic artifact.** Readable structure, no dead code, no secrets.

## 2. File tree

```
mmlsa/
├── README.md
├── CLAUDE.md
├── CONTRIBUTING.md
├── CITATION.cff
├── LICENSE                          # MIT
├── pyproject.toml
├── .gitignore
├── .env.example
├── .github/
│   ├── workflows/ci.yml
│   └── PULL_REQUEST_TEMPLATE.md
│
├── configs/
│   ├── default.yaml                 # full reference config, documented
│   ├── mini.yaml                    # development: 3 fixture texts, FakeProvider
│   ├── poc.yaml                     # Stage 1: 4 to 6 creations
│   ├── sensitivity.yaml             # Stage 2: P sweep
│   ├── full.yaml                    # Stage 3: all 49, the run of record
│   ├── control.yaml                 # Stage 5: Mode A vs Mode B
│   └── purification.yaml            # Stage 4: optional, off unless tau is unstable
│
├── data/
│   ├── corpus/                      # the N target texts, one .txt each
│   ├── noise_pool/                  # foreign texts used for noise injection
│   ├── heldout/                     # foreign + in-corpus texts, reserved
│   ├── mixture_sources/             # passages spliced in the mixture test
│   ├── function_words/
│   │   └── en_core_v1.txt           # the versioned function-word list
│   └── manifest.json                # ids, titles, word counts, sha256, provenance
│
├── src/mmlsa/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py                       # Typer app, the only place that prints
│   ├── config.py                    # Pydantic settings model
│   │
│   ├── corpus/
│   │   ├── loader.py                # load, normalize, validate
│   │   ├── gutenberg.py             # strip Project Gutenberg headers and footers
│   │   └── manifest.py              # build and verify data/manifest.json
│   │
│   ├── chunking.py                  # Step 2
│   │
│   ├── distance/
│   │   ├── base.py                  # StyleDistance protocol
│   │   ├── tokenize.py              # normalization and function-word extraction
│   │   ├── fwed.py                  # Step 4, default metric
│   │   ├── freq_vector.py           # Phase B alternative
│   │   ├── signal.py                # Phase B alternative
│   │   └── registry.py
│   │
│   ├── llm/
│   │   ├── base.py                  # LLMProvider protocol, LLMRequest, LLMResponse
│   │   ├── cache.py                 # content-addressed store
│   │   ├── ledger.py                # append-only calls.jsonl
│   │   ├── runner.py                # concurrency, rate limiting, retries
│   │   └── providers/
│   │       ├── gemini.py
│   │       ├── openai.py
│   │       ├── anthropic.py
│   │       ├── fake.py              # deterministic, for tests
│   │       └── replay.py            # cache-only, no network
│   │
│   ├── pipeline/
│   │   ├── profile.py               # Step 1, packing + extraction + merge
│   │   ├── rewrite.py               # Step 3, validation and retries
│   │   ├── score.py                 # Steps 4 and 5
│   │   ├── classify.py              # Step 6, exact Otsu + alternatives
│   │   ├── noise.py                 # foreign-creation selection per run
│   │   └── orchestrator.py          # the M-run loop, run directory lifecycle
│   │
│   ├── experiments/
│   │   ├── control.py               # Mode A vs Mode B, paired t-test
│   │   ├── sensitivity.py           # vary P, vary M
│   │   ├── mixture.py               # synthetic mixture test
│   │   ├── heldout.py
│   │   └── purification.py          # optional Phase B loop
│   │
│   ├── reporting/
│   │   ├── plots.py                 # sorted scatter, histogram, per-run variance
│   │   ├── tables.py                # scores.csv, comparison vs prior findings
│   │   └── report.py                # assemble a run report
│   │
│   └── utils/
│       ├── hashing.py, seeds.py, logging.py, tokens.py, io.py
│
├── tests/
│   ├── conftest.py                  # fixtures; blocks real providers
│   ├── unit/                        # chunking, tokenize, fwed, otsu, cache, config
│   ├── integration/                 # end-to-end on a 3-text mini corpus with FakeProvider
│   ├── contract/                    # provider protocol conformance
│   ├── data/                        # corpus integrity, disjointness of data sets
│   ├── fixtures/
│   └── test_no_hardcoded_author.py  # enforces R1
│
├── runs/                            # git-ignored except committed summaries
├── cache/                           # git-ignored
└── docs/
```

## 3. Core interfaces

Define these first. Everything else depends on them, and getting them right early prevents rewrites.

### 3.1 LLM provider

```python
# src/mmlsa/llm/base.py
from typing import Protocol
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    system: str | None = None
    temperature: float = 0.0
    max_output_tokens: int = 4096
    response_format: str = "text"  # "text" | "json"
    tag: str = ""  # "profile" | "profile_merge" | "rewrite" | "control"


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model_id: str  # requested, e.g. "gemini-2.5-flash"
    model_version: str  # as reported by the provider
    input_tokens: int
    output_tokens: int
    latency_ms: int
    finish_reason: str
    raw: dict  # provider payload, minus credentials


class LLMProvider(Protocol):
    name: str

    def context_window(self) -> int: ...
    def complete(self, request: LLMRequest) -> LLMResponse: ...
```

Every provider implementation must pass `tests/contract/test_provider_contract.py` against the same
suite. `FakeProvider` returns a deterministic transformation of the input, seeded by a hash of the
prompt, so integration tests produce stable, non-trivial deltas without a network.

### 3.2 Style distance

```python
# src/mmlsa/distance/base.py
class StyleDistance(Protocol):
    name: str

    def __call__(self, original: str, rewrite: str) -> DistanceResult: ...


@dataclass(frozen=True)
class DistanceResult:
    value: float  # in [0, 1]
    n_units_original: int  # |FW(c)| for fwed
    n_units_rewrite: int
    degenerate: bool = False
    detail: dict | None = None  # the edit script, for interpretability
```

`detail` is what makes NFR Interpretability real: for FWED it holds the aligned edit operations
(`you -> thou`, `does -> doth`), which is exactly the plain-language explanation shown to a reader.
Store it for a sampled subset of chunks, not all of them, to keep artifacts manageable.

### 3.3 Threshold classifier

```python
class Thresholder(Protocol):
    name: str

    def fit(self, scores: Sequence[float]) -> ThresholdResult: ...


@dataclass(frozen=True)
class ThresholdResult:
    tau: float
    method: str
    between_class_variance: float | None
    diagnostics: dict  # cross-check values, bimodality statistics
```

Implementations: `otsu_exact` (default), `otsu_skimage` (cross-check), `gmm_2` (fallback),
`manual` (explicit value from config).

## 4. The caching and ledger layer

This is the load-bearing piece of the architecture. Read this section before writing any provider code.

**Cache key** = `sha256` of canonical JSON over:
`provider name`, `model_id`, `temperature`, `max_output_tokens`, `response_format`, `system`, `prompt`,
and a `prompt_schema_version` integer.

Bumping `prompt_schema_version` invalidates the cache deliberately when a prompt template changes.

**Cache entry** at `cache/<key[:2]>/<key>.json`:

```json
{
  "key": "…", "request": { … }, "response": { … },
  "provider": "gemini", "model_version": "gemini-2.5-flash-002",
  "created_utc": "2026-08-04T09:12:33Z", "latency_ms": 1841,
  "input_tokens": 1180, "output_tokens": 541
}
```

**Ledger** at `runs/<run_id>/calls.jsonl`, one line per call **including cache hits**, with the cache key,
the tag, the creation id and chunk index, and whether it was a hit. This is the audit trail required by
the non-functional requirements, and it is what makes a run replayable.

**Three execution modes**, one config key `llm.mode`:

| Mode | Behaviour | Use |
|------|-----------|-----|
| `live` | cache miss calls the provider and writes the cache | normal runs |
| `replay` | cache miss is a hard error | exact reproduction, CI on recorded data |
| `refresh` | ignores the cache, always calls, overwrites | deliberate re-measurement |

**Resumability falls out of this for free.** Re-invoking an interrupted run with the same config and
run id skips every completed call. No separate checkpoint mechanism is needed. This is why the cache is
a hard rule rather than an optimization.

## 5. Concurrency

`llm/runner.py` owns all concurrency. Pipeline code submits work and receives results in
**deterministic order**, sorted by `(creation_id, chunk_index)`, regardless of completion order.

- Bounded worker pool, `llm.concurrency` (default 8).
- Token-bucket rate limiter, `llm.requests_per_minute` and `llm.tokens_per_minute`.
- Retry on 429, 500, 502, 503, 504 and timeouts: exponential backoff with full jitter,
  `llm.max_transient_retries` (default 5). Content-validation retries (Step 3) are separate and are
  counted separately.
- A permanent failure is recorded in the ledger with the error class and does not abort the run;
  the affected chunk is marked failed.
- Progress via `tqdm` on stderr, and a periodic structured log line with completed / cached / failed counts.

## 6. Run artifacts

`run_id = <UTC date>T<HHMM>-<config_hash[:8]>-s<seed>`, for example `20260812T0930-a3f91c7e-s20260731`.

```
runs/<run_id>/
├── manifest.json          # run id, git commit sha, package version, start/end UTC,
│                          # provider, model_id, model_version, seed, counts, totals
├── config.snapshot.yaml   # the fully resolved config, defaults expanded
├── profiles/
│   ├── run_1_partials.json
│   ├── run_1_merged.json
│   └── run_1_packing.json
├── chunks/<creation_id>.jsonl        # chunk_index, n_words, sha256, text
├── rewrites/run_<i>/<creation_id>.jsonl
├── deltas/run_<i>.csv                # creation_id, chunk_index, delta, n_fw_orig, n_fw_rew, status
├── scores.csv                        # creation_id, title, n_chunks, s_1..s_M, score_mean,
│                                     # score_std, label, borderline
├── threshold.json                    # tau, method, diagnostics, cross-check
├── noise_diagnostics.csv             # score of each injected foreign creation
├── figures/                          # sorted_scatter.png, histogram.png, run_variance.png
├── calls.jsonl
└── logs/run.log
```

**What goes into git.** `manifest.json`, `config.snapshot.yaml`, `scores.csv`, `threshold.json`,
`noise_diagnostics.csv` and `figures/` are small and are committed, because the book commits the project
to publishing result files. `chunks/`, `rewrites/`, `deltas/` and `calls.jsonl` are large: gzip them and
attach to a GitHub release, with the release URL recorded in `manifest.json`. `cache/` is never committed.

## 7. Configuration

One Pydantic model, one YAML file, CLI overrides on top. Precedence: CLI > env > YAML > defaults.
The resolved config is hashed into the run id and snapshotted into the run directory.

Key groups: `corpus`, `chunking`, `profile`, `rewrite`, `distance`, `aggregate`, `classify`, `noise`,
`llm`, `run`, `report`, `experiment`, `purification`. See `configs/default.yaml` for the annotated
reference.

### 7.1 Config inheritance (`extends`)

Every config other than `default.yaml` declares a parent:

```yaml
extends: default.yaml     # path relative to the configs/ directory
```

`extends` is a **loader directive, not a config field.** The loader resolves it before validation and
removes it from the mapping, so the Pydantic model must not declare it. A model that rejects unknown
keys will otherwise fail on every shipped config.

Resolution rules:

1. **Recursive.** Chains are permitted and used: `sensitivity.yaml` extends `poc.yaml` extends
   `default.yaml`; `purification.yaml` extends `full.yaml` extends `default.yaml`. Resolve the parent
   fully, then apply the child.
2. **Deep merge for mappings, replacement for everything else.** A child that sets `chunking.P` leaves
   `chunking.min_chunk_words` untouched. A child that sets `experiment.sensitivity.P_values` replaces
   the whole list. Lists are never concatenated, because a merged `include_ids` would silently widen a
   run.
3. **`null` is a value, not an absence.** `include_ids: null` in a child means the whole corpus, and
   overrides a parent's subset.
4. **Cycles are a startup error**, reported with the full chain. Depth is capped at 8.
5. **Only the fully resolved mapping is validated, hashed and snapshotted.** Two configs that resolve
   identically must produce the same run id, whatever their inheritance path. The snapshot in the run
   directory is the flattened result, with no `extends` key, so a run is reproducible from its snapshot
   alone without the parent files.

Two rules:
- **No magic numbers in code.** If a value could reasonably change, it is a config key.
- **The provider is one key.** `llm.provider: gemini | openai | anthropic | fake | replay`.
  Nothing in `src/mmlsa/pipeline/` may import a concrete provider.

## 8. CLI surface

```
python -m mmlsa corpus fetch                 # download and normalize sources
python -m mmlsa corpus verify                # checksums, counts, set disjointness
python -m mmlsa profile   --config C [--run i]
python -m mmlsa chunk     --config C
python -m mmlsa rewrite   --config C --run i
python -m mmlsa score     --config C
python -m mmlsa classify  --config C
python -m mmlsa run       --config C         # the whole thing, M runs, resumable
python -m mmlsa report    --run-id R
python -m mmlsa experiment control    --config configs/control.yaml
python -m mmlsa experiment sensitivity --config configs/sensitivity.yaml
python -m mmlsa experiment mixture     --config C
python -m mmlsa experiment heldout     --config C
python -m mmlsa cache stats | prune
```

Global flags: `--provider`, `--mode {live,replay,refresh}`, `--seed`, `--limit N`, `--dry-run`, `--verbose`.

`--dry-run` resolves the config, packs the profile calls, enumerates every chunk, and prints the exact
call count and token estimate **without issuing a single request**. Run this before every wide job.

## 9. Dependencies

Named in the approved book, so keep the list close to it.

**Runtime:** `typer`, `pydantic`, `pyyaml`, `numpy`, `pandas`, `python-Levenshtein`, `scikit-image`,
`scikit-learn`, `scipy`, `matplotlib`, `seaborn`, `tqdm`, `tenacity`, `python-dotenv`, plus exactly one
provider SDK per configured provider (`google-genai`, `openai`, `anthropic`), declared as optional extras.

**Dev:** `pytest`, `pytest-cov`, `ruff`, `mypy`, `hypothesis`.

Adding anything else requires a line in `docs/DECISIONS.md`.

## 10. What not to build

Scope discipline matters more than features here.

- No web interface, no dashboard, no database. The book removed the customer-interface section
  deliberately: this is a research pipeline.
- No custom LLM abstraction framework. The provider protocol is about forty lines.
- No distributed execution. A bounded thread pool on one machine is sufficient at this scale.
- No premature Phase B metrics. Build the registry, implement `fwed`, and add alternatives when the
  comparison experiment is actually scheduled.
