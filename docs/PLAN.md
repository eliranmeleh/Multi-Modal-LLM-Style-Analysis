# PLAN — Implementation Milestones

Build order, with an acceptance criterion for every milestone. A milestone is done when its criterion is
demonstrably met, not when the code exists.

**Ordering principle:** everything deterministic is built and tested before anything touches an API.
By the end of M4 the whole pipeline runs end to end with zero API calls, using `FakeProvider`. Only then
is a single real call made. This keeps debugging cheap and keeps the first real run from being the first
integration test.

Mark progress by editing the checkboxes in this file.

---

## Phase 0 — Foundation (no LLM)

### [x] M0. Repository skeleton

Create the tree from `docs/ARCHITECTURE.md` section 2. `pyproject.toml` with the dependency groups.
Ruff, mypy, pytest configured. GitHub Actions running lint plus tests on push. `.env.example`, `.gitignore`,
MIT `LICENSE`, `README.md`. Copy `CLAUDE.md` and `docs/` into place.

**Accept:** `pip install -e ".[dev]"` succeeds, `python -m mmlsa --help` prints the command list,
`pytest -q` passes with zero tests collected as an error, CI is green on the first push.

### [x] M1. Config and logging

Pydantic settings model covering every group in `configs/default.yaml`. Precedence CLI > env > YAML >
defaults. Resolution of the `extends` directive per `docs/ARCHITECTURE.md` section 7.1, including the
two-level chains used by `sensitivity.yaml` and `purification.yaml`. Config hashing for the run id.
Structured logging. Secrets read from environment only.

**Accept:** a unit test asserts that two semantically identical configs hash the same and that changing
any single key changes the hash. Every file in `configs/` loads, resolves and validates, which is the
test that catches a key added to a child config but never declared in the model. A cycle in `extends`
raises at startup rather than recursing. `python -m mmlsa run --config configs/poc.yaml --dry-run`
resolves and prints the flattened config without touching data.

### [x] M2. Corpus acquisition and normalization

`corpus_sources.yaml` populated with the exact 49 titles and Gutenberg identifiers taken from the
reference paper. Downloader, Gutenberg boilerplate stripping, normalization per `docs/DATA.md` section 4,
manifest generation and verification. Noise pool, held-out set and mixture sources assembled.

**Accept:** `python -m mmlsa corpus verify` passes. The manifest lists 49 target texts with word counts
inside their sanity bands, the total falls in the expected 0.9 to 1.0 million word range, no Gutenberg
marker survives in any normalized file, and the set-disjointness test passes.

> This milestone is the one most likely to be underestimated. Text acquisition and cleaning is where
> silent errors enter. Budget real time for it and eyeball several normalized files by hand.

> **Done, 2026-08-15.** `corpus verify` passes 70 checks. 49 creations, 1,065,092 words.
>
> The warning about it being underestimated was correct. Four things had to be resolved that the
> plan did not anticipate, and all four are recorded rather than papered over:
>
> 1. **The reference paper gives titles, not Gutenberg identifiers** (`OPEN_QUESTIONS.md` Q12). The
>    edition family was reconstructed from which series contains the paper's unusual entries, and
>    every identifier was checked against the Gutenberg catalogue. Two identifiers taken from memory
>    were wrong and were caught by that check.
> 2. **Locrine and Mucedorus are one creation in the paper and two on Gutenberg** (Q13), so they are
>    concatenated to preserve N = 49.
> 3. **Eyeballing the files by hand found a real bug**, exactly as the plan warned. The scene lists
>    and cast lists were surviving, because the first "ACT I" in these files is a contents entry, not
>    the play. The rule now anchors on the cast list. It fires on 46 of 49; the three it skips are
>    the poems, which have neither.
> 4. **The corpus is 1.065 million words, not the estimated 0.9 to 1.0 million.** Measured rather
>    than assumed: speaker prefixes, stage directions and headings are 10.2 percent of it, and the
>    spoken text is 956,416 words. See `docs/RESULTS.md` F-00.

### [x] M3. Chunking, tokenizer and FWED

Step 2 and Step 4 as pure functions. Function-word list committed. Private-use-area code point mapping
for sequence Levenshtein. Distance registry with `fwed` registered.

**Accept:** all of the following pass.
- Full-coverage property: concatenating a creation's chunks reproduces its word sequence exactly, with no
  loss, no duplication and no reordering, for every text in the corpus.
- Chunk sizes are all `P` except possibly the last.
- `delta(x, x) == 0` for every chunk in the corpus.
- `delta(c, r) == delta(r, c)` on random pairs (`hypothesis`).
- `0 <= delta <= 1` always.
- At least one hand-computed golden case whose arithmetic is written out in the test docstring.
- The fast Levenshtein path agrees with a pure-Python dynamic-programming reference on 1,000 random
  sequence pairs.

> **Done, 2026-08-15.** All criteria pass. The two that say *"for every text in the corpus"* are
> checked over the real 49 creations in `tests/data/test_corpus_integrity.py`: the full-coverage
> round trip at P = 200, 400 and 600, and `delta(x, x) == 0` over all 2,600-odd chunks. No chunk in
> the corpus is degenerate.
>
> Implementing this milestone surfaced two findings, both recorded rather than silently resolved:
> the function-word list has no wh-adverbs (`docs/OPEN_QUESTIONS.md` Q10), and the documented worked
> example in `docs/DATA.md` section 5.3 disagreed with the list it was illustrating. The example was
> corrected to the list, not the other way round.

### [x] M4. Aggregation and exact Otsu

Step 5 and Step 6 as pure functions. Exact Otsu over the sorted scores, plus the `skimage` cross-check,
plus a two-component Gaussian-mixture alternative. Borderline banding. Sorted-scatter and histogram plots.

**Accept:**
- On a synthetic two-cluster dataset with a known separation, exact Otsu recovers the correct split.
- Exact Otsu and `skimage.filters.threshold_otsu` agree within tolerance on the same data.
- On a deliberately unimodal dataset, the bimodality diagnostic fires and the run is flagged.
- `scores.csv`, `threshold.json` and the scatter figure are produced from synthetic scores.

---

## Phase 1 — LLM layer

### [x] M5. Provider protocol, cache, ledger, runner

`LLMProvider` protocol. `FakeProvider` (deterministic, seeded by prompt hash, produces non-trivial and
reproducible rewrites). `ReplayProvider`. Content-addressed cache. Append-only ledger. Bounded-concurrency
runner with rate limiting, backoff and deterministic result ordering.

**Accept:**
- Contract test suite passes for `FakeProvider` and `ReplayProvider`.
- Cache hit-then-miss test: the same request twice issues one provider call.
- Changing `prompt_schema_version` produces a cache miss; changing nothing produces a hit.
- `replay` mode raises on a cache miss.
- Ledger lines validate against the schema and include cache hits.
- Killing a run mid-flight and restarting it with the same run id issues no duplicate calls.

> **Done, 2026-08-15.** All six criteria pass, and the resume property is checked directly: a run
> killed after 17 of 40 calls, restarted with the same run id, issues exactly 23. A third invocation
> issues none. 97 per cent coverage on `src/mmlsa/llm/`.
>
> One defect was found by the tests rather than in production. Identical prompts produce identical
> cache keys by design, so parallel workers race to write one entry, and on Windows the loser of that
> race gets a `PermissionError` from the rename. Recorded as `docs/DECISIONS.md` I20 and covered by
> `test_identical_prompts_across_creations_race_on_one_cache_entry_safely`.

### [x] M6. Step 1, profile extraction

Token estimation, deterministic bin packing of whole creations, `k` extraction calls, merge call when
`k > 1`, structured profile parsing with a free-text fallback, profile artifacts written per run.

**Accept:** on the mini corpus with `FakeProvider`, a merged profile JSON with the six keys is produced;
packing is identical across two invocations; no creation is split across bins; the rendered prompt passes
the neutrality test.

> **Done, 2026-08-15.** All four criteria pass. Measured on the real corpus: 1,437,851 estimated
> tokens, giving `k = 3` extraction calls at a one-million-token window, inside the 2 to 4 that
> `docs/DECISIONS.md` I3 predicted.
>
> The neutrality test found a real leak in our own code, not in a template: two `src/` docstrings
> named a historical period. The forbidden-term list was also widened, because it listed the
> three-word form of the period name and the two-word form went straight through it.

### [x] M7. Step 3, rewriting

Chunk rewrite worker, preamble stripping, the four validation checks, retry policy, failure accounting.

**Accept:** on the mini corpus with `FakeProvider`, every chunk gets a rewrite; injected pathological
responses (empty, refusal, half-length, fully paraphrased, fenced, preambled) each trigger the expected
branch, verified by unit tests; the failed-chunk accounting appears in the run manifest.

> **Done, 2026-08-15.** All three criteria pass, with one test per pathological response, including
> the case that is easy to get backwards: a rewrite identical to the original is **accepted**.
>
> `tests/integration/test_pipeline_end_to_end.py` now runs all six steps over the mini corpus with no
> provider, which is what proves the seams fit before M8 relies on them.
>
> A defect was found in this milestone's own specification. The preamble pattern read
> `here (is|'s)`, with a space before the group, so it matched "here 's" and not the contraction
> "here's". An unstripped preamble does not fail loudly; it is measured as part of the passage and
> inflates that chunk's delta, which is exactly the false positive the validation exists to prevent.
> Corrected in `docs/SPEC.md` and recorded as `docs/DECISIONS.md` I23.

### [x] M8. Orchestrator, `M` runs and noise injection

The full `M`-run loop. Deterministic noise-creation selection, run 1 plain, non-cumulative. Noise text
profiled, scored as a diagnostic, and excluded from `tau` and from the reported set. Immutable run
directories.

**Accept:** `python -m mmlsa run --config configs/mini.yaml --provider fake` produces a complete run
directory matching the layout in `docs/ARCHITECTURE.md` section 6. Two runs with the same config and seed
produce identical `scores.csv`. The noise diagnostic file lists exactly `M - 1` foreign texts, all distinct.

> **Note from M7.** With `FakeProvider` and **no noise injected**, the `M` runs are byte-identical by
> construction: the same corpus gives the same profile, which gives the same rewrite prompts, which
> hit the cache. The end-to-end test at M7 duly reports a per-creation standard deviation of exactly
> zero. That is correct behaviour, but it means run-to-run variation is currently exercised
> structurally and not numerically. **The M8 tests must inject noise**, since that is what makes the
> profile — and therefore the deltas — differ between runs offline. Without it, the averaging in
> Step 5 would be tested against `M` copies of one number.

> **Done, 2026-08-15.** All three criteria pass, plus the M7 note above: the runs do differ, because
> noise injection changes the corpus in run 2, which changes the profile, which changes every rewrite
> prompt. Per-creation standard deviations are non-zero.
>
> `FakeProvider` had to be corrected for this. It returned a constant profile regardless of the
> corpus it was shown, so injecting noise changed the extraction prompt but not the profile, and
> every rewrite in run 2 was a cache hit. The fake now derives one figure in the profile from the
> prompt hash, which is the smallest change that makes it vary for the right reason.
>
> The dry-run planner was checked against reality rather than trusted: `plan_run` predicts the call
> count exactly, asserted by `test_the_dry_run_plan_predicts_the_call_count`. That is what makes it
> safe to approve a wide job from the plan alone.
>
> `configs/poc.yaml` named five creation identifiers that never existed, having been written before
> the corpus was assembled. `mmlsa run --dry-run` refused it, which is how it was found.

> **This is the point at which the pipeline is finished.** Everything after it is measurement.

---

## Phase 2 — Real measurement

### [ ] M9. First real call and provider validation

Wire the real providers. Make one profile call and ten rewrite calls against each candidate model.
Inspect the rewrites by hand: is content preserved, is the register actually shifted, is the output clean.

**Accept:** a short written comparison of the candidate models on ten identical chunks, covering rewrite
fidelity, output cleanliness and latency. This is evidence for the model-choice decision that the book
defers to the proof of concept.

> **Half done, 2026-08-16.** All three backends are implemented, registered and tested — 61 tests
> against stub SDKs, no network. The acceptance criterion is a *measured* comparison, so the milestone
> stays open until a key exists. What is ready: `llm.provider` selects any of the three, each behind
> its own optional extra; `.env` is now actually loaded (it never was); `llm.temperature` and
> `llm.timeout_seconds` now reach a request (they never did).
>
> Three things surfaced that the book could not have anticipated, all recorded rather than absorbed.
> **`temperature = 0` is rejected outright by several current models** — `docs/OPEN_QUESTIONS.md` Q14.
> **Reasoning tokens are charged against the output budget**, so a rewrite call can spend its whole
> allowance thinking and return nothing; each provider holds reasoning at the lowest value its model
> permits. **An empty completion would score as delta 1.0**, the maximum the metric can produce, making
> a creation look maximally suspicious for a reason unrelated to its author; it is now a recorded
> failure instead — `docs/DECISIONS.md` I24.
>
> When the key arrives, start here: `pip install -e ".[gemini]"`, put `GEMINI_API_KEY` in `.env`, then
> `python -m mmlsa run --config configs/mini.yaml --dry-run` before anything else.

> **Harness done, 2026-08-16.** `python -m mmlsa compare` produces the acceptance artifact. Every
> candidate rewrites the **same** deterministically selected chunks, and the command writes
> `summary.md` (the written comparison), `comparison.csv`, `rewrites/` (each passage with every
> model's version beneath it, for the manual read `docs/TESTING.md` section 7 requires), `profiles/`
> and `calls.jsonl`. It prints its plan and issues nothing without `--yes`.
>
> A candidate that cannot be built — no extra, no key — is recorded against that candidate and the
> others still run, which is the normal case while only one provider has a key. Exercised end to end
> against the mini corpus offline; the milestone still needs a key for the numbers to mean anything.
>
> ```
> python -m mmlsa compare --config configs/mini.yaml \
>     -m gemini:gemini-2.5-flash -m openai:gpt-4.1-mini --chunks 10
> ```

### [ ] M10. Stage 1, proof of concept

Book section 4.3 Stage 1. Four to six creations including a known mixed-authorship case (Henry VIII) and
a confirmed pure case (Macbeth). Full `M` runs.

**Accept:** scores, scatter plot and a written finding. The honest outcome is either "the deltas separate
the known cases" or "they do not, and here is the evidence". A negative result at this stage is
information, and it is far cheaper here than after the full run. Report it to the supervisors either way.

### [ ] M11. Stage 2, reproducibility and sensitivity

`M` independent runs on identical inputs; per-creation score stability and standard deviation.
Sweep `P` over 200, 300, 400, 500, 600 and check that classifications hold.

**Accept:** a stability table (per-creation mean, standard deviation, coefficient of variation), a
`P`-sweep table showing label changes as a function of `P`, and a recommendation for `M`. If the
coefficient of variation is large on a non-trivial fraction of chunks, raise `M` and repeat, as the book
requires.

### [ ] M12. Stage 3, full corpus run

All 49 creations, single round, `M` runs. Sorted scatter with `tau`, the suspicious set, per-creation
confidence.

**Accept:** the committed result artifacts, plus an agreement table against the prior published findings
reporting both agreements and disagreements. Disagreement is an acceptable and reportable outcome.

### [ ] M13. Stage 5, control experiment

Mode A versus Mode B on a sampled chunk set, paired by chunk. Paired t-test at `alpha = 0.05`, Cohen's
`d`, Wilcoxon signed-rank as backup.

**Accept:** the reported statistics and a clear verdict on success metric 2. If the profile does not
contribute significantly, that finding is reported, not buried: it would mean the method is riding on the
model's memorized prior, and the book's stated fallback is a held-out non-canonical corpus.

### [ ] M14. Validation test suite

The four checks from `docs/SPEC.md` section 7 implemented as automated tests: calibration, synthetic
mixture, held-out generalization, noise robustness. Plus the no-added-noise variant for comparison.

**Accept:** `pytest tests/validation -q` runs each check against recorded run artifacts in replay mode and
reports pass or fail against the stated conditions. The book promises that future researchers can re-run
the verification with a single command, so this must genuinely be one command.

### [ ] M15. Reporting and repository finalization

Run report generator, all figures, `README.md` with results and reproduction instructions, artifact
release, final `docs/OPEN_QUESTIONS.md` sweep.

**Accept:** a clean clone plus `python -m mmlsa run --config configs/full.yaml --mode replay` reproduces
the published `scores.csv` byte for byte from the released artifacts.

---

## Phase 3 — Optional, only if warranted

### [ ] M16. Distance-metric comparison

Implement `fw_freq_cosine` and `signal`. Score the **same recorded rewrites** with every metric, so no
additional LLM calls are needed. Compare separation quality.

### [ ] M17. Iterative purification

Only if M11 or M12 shows the single-round threshold to be unstable. Implement the bounded loop from
`docs/SPEC.md` section 4 and report inter-iteration set differences.

---

## What to do in the first week

1. Read `docs/SPEC.md` end to end. It is the contract.
2. Extract the exact 49-title corpus list from the reference paper into `data/corpus_sources.yaml`.
   Nothing downstream is trustworthy without it.
3. M0, M1, M3 in that order. M3 is satisfying and entirely offline: real chunking and a real, tested
   distance metric on real text, with no API key needed.
4. Decide who owns which half of the work. A natural split is one person on the deterministic core
   (M3, M4, M14) and one on the LLM layer (M5, M6, M7), meeting at M8.
5. Get API keys for at least two candidate providers so M9 can actually compare them.

**Do not** start with the LLM integration. It is the most fun and the least useful thing to have working
first, because without M3 and M4 there is nothing to do with the responses.
