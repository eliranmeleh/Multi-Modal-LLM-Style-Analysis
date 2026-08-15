# TESTING

The test suite has two jobs. The first is ordinary software correctness. The second is protecting the
**scientific validity** of the results, because a bug in the deterministic core does not crash anything:
it quietly produces plausible wrong numbers that end up in a graded report.

---

## 1. Layout

```
tests/
├── conftest.py                     # fixtures; blocks real providers
├── unit/                           # pure functions, no I/O
│   ├── test_config.py
│   ├── test_normalization.py
│   ├── test_chunking.py
│   ├── test_tokenize.py
│   ├── test_function_words.py
│   ├── test_fwed.py
│   ├── test_aggregate.py
│   ├── test_otsu.py
│   ├── test_cache.py
│   ├── test_ledger.py
│   ├── test_noise_selection.py
│   ├── test_rewrite_validation.py
│   └── test_prompt_neutrality.py
├── contract/test_provider_contract.py
├── integration/
│   ├── test_pipeline_end_to_end.py    # mini corpus + FakeProvider
│   └── test_resume.py                 # interrupt and restart
├── data/
│   ├── test_corpus_integrity.py
│   └── test_set_disjointness.py
├── validation/                     # the four scientific checks, replay mode
│   ├── test_calibration.py
│   ├── test_mixture.py
│   ├── test_heldout.py
│   └── test_noise_robustness.py
├── test_no_hardcoded_author.py
└── fixtures/
    ├── mini_corpus/                # 3 short public-domain texts
    └── recorded_runs/              # cached responses for replay tests
```

## 2. Global guardrails

**No test may reach the network.** `conftest.py` installs an autouse fixture that removes
`GEMINI_API_KEY`, `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` from the environment unless
`MMLSA_ALLOW_LIVE=1` is set, which CI never sets. The live providers read their key at **construction**
for exactly this reason: without one they raise immediately, so a stray live configuration in a test
fails with a clear message instead of issuing a billable request. `test_live_providers.py` asserts that
failure for all three, and replaces each SDK with a stub so the adapters can still be exercised in
full offline.

**No hard-coded author name in `src/`.** `test_no_hardcoded_author.py` walks `src/mmlsa/**/*.py` and
fails on a case-insensitive match for the target author's name or any corpus-specific title. The
forbidden list is loaded from `tests/forbidden_terms.txt`, not from the source tree. This is how the
generalizability requirement becomes enforceable rather than aspirational.

**Prompt neutrality.** `test_prompt_neutrality.py` renders every pipeline template with realistic
placeholder values and asserts that no forbidden term appears. The control experiment's Mode B template
is the single allowed exception and is listed explicitly.

## 3. Exact expectations for the deterministic core

These are the tests that protect the numbers. Write them before the implementation.

### Config resolution
- **Every shipped config loads.** Parametrize over every file in `configs/`: each one resolves its
  `extends` chain and validates against the model. This is the test that catches a key present in a child
  config but never declared in the model, which is otherwise found only when the experiment is run.
- **Chains resolve in order.** `sensitivity.yaml` inherits `corpus.include_ids` from `poc.yaml` and
  `chunking.P` from `default.yaml`, and its own `run.M` wins over both.
- **Merge semantics.** A child setting one key inside a mapping leaves the sibling keys of that mapping
  intact. A child setting a list replaces it rather than extending it. A child setting `null` overrides a
  non-null parent value.
- **`extends` never reaches the model.** The resolved mapping contains no `extends` key, and the run
  snapshot is loadable on its own with no parent file present.
- **Hash is a function of the resolved values.** Two configs that flatten to the same mapping hash the
  same whatever their inheritance path, and changing any single effective key changes the hash.
- **Cycles fail loudly.** A config that extends itself, directly or transitively, raises at startup with
  the chain in the message rather than recursing until the stack ends.

### Chunking
- **Round trip.** For every text in the corpus, concatenating the chunk word lists reproduces the source
  word list exactly. No loss, no duplication, no reordering.
- **Sizes.** All chunks have exactly `P` words except possibly the last, which has between 1 and `P`.
- **Count.** `n_chunks == ceil(n_words / P)`.
- **Determinism.** Chunking the same text twice gives byte-identical chunks.
- **Edge cases.** A text shorter than `P` yields one chunk. An empty text raises, it does not yield zero
  chunks silently.

### Tokenization and function words
- Punctuation is stripped from token edges but apostrophes survive: `"'tis,"` tokenizes to `'tis`.
- Case folding: `The` and `the` both match.
- Order is preserved and duplicates are kept: this is a sequence, not a set.
- A token not in the list is dropped, including content words.
- The list file is lowercase, deduplicated, sorted, and between 110 and 130 entries.

### FWED
- `delta(x, x) == 0` for every chunk in the real corpus, not just for a toy string.
- Symmetry on random pairs (`hypothesis`).
- Range `[0, 1]` always.
- Both sequences empty gives `0.0` and `degenerate == True`.
- One sequence empty and the other not gives `1.0`.
- **At least one hand-computed golden case**, with the arithmetic written out in the test docstring:
  the two function-word sequences, the edit operations, the numerator, the denominator, the result.
  Compute it by hand and pin it. Never copy a number from documentation without re-deriving it.
- The private-use-area fast path agrees with a pure-Python dynamic-programming reference on 1,000
  randomly generated sequence pairs.

### Aggregation
- Mean over chunks matches a hand-computed small case.
- Mean over runs matches a hand-computed small case.
- Sample standard deviation uses `ddof = 1`.
- Failed chunks are excluded from the mean, and the divisor is the count of successful chunks.
- A creation with all chunks failed produces no score and is reported, rather than producing `NaN` that
  propagates into the threshold.

### Otsu
- On a synthetic two-cluster set with a known gap, the exact method recovers the correct split.
- Exact and `skimage` agree within tolerance on the same data.
- `tau` lies strictly between the two clusters.
- Ties classify as authentic (`score > tau` is strict).
- A unimodal input triggers the bimodality flag.
- With `N` distinct values, exactly `N - 1` candidate splits are evaluated.

### Cache and ledger
- Same request twice issues one provider call.
- Changing any keyed field, including `prompt_schema_version`, produces a miss.
- `replay` mode raises on a miss.
- `refresh` mode always calls and overwrites.
- Every call, including cache hits, appends exactly one ledger line, and lines validate against the schema.
- The cache key is stable across processes and across machines.

### Noise selection
- Run 1 gets no noise text.
- Runs 2 to `M` get `M - 1` distinct texts.
- Selection is a deterministic function of the seed.
- No selected text is a member of the target corpus.

### Rewrite validation
One test per pathological response, each asserting the expected branch:
empty, whitespace only, a refusal, a chatty preamble, a Markdown code fence, half the original length,
double the original length, a full paraphrase with the content words replaced, and an unchanged copy of
the input (which must be **accepted**, giving `delta = 0`).

## 4. Integration tests

**Mini corpus:** three short public-domain texts in `tests/fixtures/mini_corpus/`, a few hundred words
each, so a full `M = 2` run takes seconds with `FakeProvider`.

`FakeProvider` must be deterministic and non-trivial: seed a small random generator from the hash of the
prompt and apply a fixed set of function-word substitutions at a rate that differs by input, so that the
resulting deltas are stable, reproducible and not all zero. A fake that echoes its input makes every delta
zero and tests nothing downstream.

- **End to end.** A full run produces every artifact in the layout, and two runs with the same config and
  seed produce identical `scores.csv`.
- **Resume.** Kill the run after `n` calls, restart with the same run id, and assert that the provider
  call count for the second invocation equals the number of remaining calls, not the total.
- **Provider swap.** Changing only `llm.provider` in the config runs without touching pipeline code.

## 5. Validation tests (the scientific checks)

These run against recorded run artifacts in `replay` mode, so they are fast, offline and deterministic.
They implement `docs/SPEC.md` section 7 and are what the book means by "future researchers can re-run the
verification with a single command".

| Test | Assertion |
|------|-----------|
| `test_calibration` | Coefficient of variation of repeated deltas on the sample stays below the configured bound on the large majority of chunks. |
| `test_mixture` | Spliced texts are classified suspicious, and per-chunk delta peaks coincide with the known splice positions within a tolerance of one chunk. |
| `test_heldout` | The finalized pipeline classifies the reserved held-out texts correctly. |
| `test_noise_robustness` | Authentic labels are unchanged between the with-noise and without-noise variants for every non-borderline creation. |

Each prints the measured value next to the pass condition, so a failure is immediately interpretable.

## 6. Coverage and CI

- Coverage target: 90 percent on `src/mmlsa/distance/`, `chunking.py`, `pipeline/score.py`,
  `pipeline/classify.py`, `llm/cache.py`. These are the modules where a bug is silent.
- Elsewhere, coverage is a signal, not a target. Do not write tests to hit a number.
- CI on every push: `ruff check`, `ruff format --check`, `mypy src`, `pytest tests/unit tests/contract
  tests/integration tests/data -q`. The `validation/` suite runs only when recorded artifacts are present.
- CI runs on Ubuntu with Python 3.11 and holds no API keys.

## 7. Manual checks that no test replaces

Automation cannot catch these. Do them by hand and write down what you saw.

1. **Read twenty rewrites side by side with their originals** after M9. Is the content actually preserved?
   Is the style actually shifting? Is the model quietly modernizing spelling, which would inflate every
   delta uniformly and could look like a working method while measuring nothing?
2. **Read the extracted profile.** Does it describe a real style, or is it generic filler that would fit
   any English text? A vacuous profile makes the control experiment the whole story.
3. **Look at the sorted scatter before reading the labels.** Is there a visible gap, or are you about to
   report a threshold through the middle of a single cloud?
4. **Inspect the highest-delta and lowest-delta chunks.** Both extremes are where bugs surface first.
