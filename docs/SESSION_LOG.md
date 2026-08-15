# SESSION LOG

Append-only. One entry per working session, newest at the top. Never edit or delete a past entry;
if something recorded here turns out to be wrong, say so in a later entry.

This is the project's memory. `docs/STATUS.md` says where we are *now*; this file says how we got
here and, crucially, **why** — the reasoning that would otherwise be lost between sessions.

**Entry template**

```
## YYYY-MM-DD — <one-line goal>

**Goal.** What this session set out to do.
**Done.** What actually changed, with file paths.
**Verified.** The command that proves it, and its result. Not "it should work".
**Decided.** Any judgement call taken, and why. Cross-reference docs/DECISIONS.md if it is durable.
**Surprised by.** Anything that did not behave as expected. This is the highest-value line.
**Next.** The single next action, concretely enough to start cold.
```

---

## 2026-08-15 (fifth) — M7: Step 3, rewriting, and the pipeline closes

**Goal.** Build Step 3 and the response handling that protects the measurement, then wire all six
steps together to check the seams fit.

**Done.**
- `src/mmlsa/pipeline/rewrite.py`: cleaning (fences, preamble), the four specified validation checks,
  batched retries, per-creation failure accounting, and `to_chunk_deltas` as the seam into Step 5.
- `src/mmlsa/utils/text.py`: fence stripping, shared with Step 1 rather than duplicated.
- `tests/unit/test_rewrite_validation.py`: one test per pathological response.
- `tests/integration/test_pipeline_end_to_end.py`: all six steps over the mini corpus, no provider.

**Verified.**
- `pytest`: **488 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean. 96 per cent
  coverage on `rewrite.py`.
- Every pathological response named in `docs/TESTING.md` triggers its expected branch: empty,
  whitespace-only, fence-only, four refusal forms, half length, double length, full paraphrase,
  preamble, fence, fence-plus-preamble. And an unchanged copy of the input is **accepted**.
- The mini corpus runs end to end: three creations, two runs, 15 calls, a threshold with
  separability 0.893 and no flags.

**Decided.**
- Content retention is the **overlap coefficient over content-word types**, not Jaccard and not over
  tokens. Types because the question is whether the subject matter survived; overlap rather than
  Jaccard because a rewrite that legitimately adds a few words should not be penalised for the
  addition. Requiring token frequencies to survive would forbid the very rewriting the method asks
  for, since frequencies are the style signal.
- Retries are **batched by round** rather than serial per chunk, so concurrency survives a retry.

**Surprised by.** Two things, one a defect and one a hole in the test strategy.

1. **The preamble pattern in our own specification does not match "here's".** It reads
   `here (is|'s)`, with a space before the group, so it matches "here 's" and misses the contraction
   — which is the commoner of the two openings. Corrected in `docs/SPEC.md`, recorded as
   `DECISIONS.md` I23. What makes this worth dwelling on is the failure mode: an unstripped preamble
   does not raise anything. It is measured as part of the passage and inflates that chunk's delta,
   which is precisely the false positive the validation exists to prevent. A defect in the guard is
   worse than no guard, because it is invisible.

2. **With `FakeProvider` and no noise, the `M` runs are byte-identical by construction.** Same
   corpus gives the same profile, which gives the same rewrite prompts, which hit the cache. The
   end-to-end test duly reports a per-creation standard deviation of exactly zero. That is correct
   behaviour and not a bug, but it means run-to-run variation is currently exercised structurally
   and not numerically. **M8's tests must inject noise**, which is what makes the profile differ
   between runs offline. Noted in `docs/PLAN.md` under M8 so it cannot be forgotten.

Also worth recording: on the mini corpus the direction of the measurement is right. `mini_alpha`,
written with older function-word usage, scores lowest (0.0123); `mini_beta`, the same scene in modern
usage, scores highest (0.0413). `FakeProvider` substitutes modern forms for older ones, so a text
already in the older register needs the least change. That is a sanity signal, not a result.

**Next.** M8: the orchestrator, the `M`-run loop, deterministic noise selection, immutable run
directories, and `mmlsa run` actually running. `docs/PLAN.md` calls this the point at which the
pipeline is finished and everything after it is measurement.

---

## 2026-08-15 (fourth) — M6: Step 1, profile extraction

**Goal.** Build Step 1: take the whole corpus, pack it into as many calls as the context window
allows, extract a partial profile from each, and merge them into one.

**Done.**
- `src/mmlsa/prompts/`: the book's six templates as versioned files, plus rendering, profile
  serialization and the version map that feeds the cache key.
- `src/mmlsa/utils/tokens.py`: token estimation and deterministic first-fit-decreasing packing of
  whole creations.
- `src/mmlsa/pipeline/profile.py`: extraction, the merge call, structured parsing with a free-text
  fallback, and the per-run artifact record.
- `tests/fixtures/mini_corpus/`: three short locally authored texts, plus `mini_sources.yaml`, so
  `configs/mini.yaml` actually resolves. The loader now honours `corpus.dir` and supports texts with
  no Gutenberg origin.

**Verified.**
- `pytest -q`: **435 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean.
- All four M6 criteria: a merged profile with the six keys is produced from the mini corpus under
  `FakeProvider`; packing is identical across invocations and independent of input order; no
  creation is split across calls; every rendered pipeline prompt passes the neutrality scan.
- A built wheel contains all six templates and `versions.json`, so the prompts survive packaging.
- Real corpus: 1,437,851 estimated tokens, `k = 3` calls at a one-million-token window. Recorded as
  `docs/RESULTS.md` F-00b.

**Decided.**
- **Creation identifiers are not rendered into the extraction prompt.** The creations are numbered
  positionally and the packing record maps positions back to identifiers. A title is as much of a
  cue as an author's name, and this is the specific way a neutral template could have leaked.
- **An unparseable profile response falls back to free text rather than failing the run.** The
  book's literal form is free text anyway, so a formatting slip is not worth losing a run over. The
  fallback is logged so it is visible rather than silent.
- **Locally authored fixtures declare `gutenberg_id: null`.** Inventing identifiers for them would
  put numbers that look like provenance into the manifest.

**Surprised by.** The neutrality test found a leak in **our own code**, not in a template.

Two `src/` docstrings named a historical period: one in `utils/tokens.py` explaining why the token
estimate is conservative, one in `distance/tokenize.py` explaining why apostrophes survive. Both were
written as helpful context and both are exactly what R1 forbids, because the claim being defended is
that the method transfers to any author's corpus.

Worse, the forbidden-term list only caught one of them. It listed the three-word form of the period
name, so the two-word form went straight through. The list has been widened. The lesson is that a
guard rail is only as good as its list, and the list needs the *shortest* form of a term, not the
most complete one.

**Next.** M7, Step 3 rewriting: the chunk rewrite worker, preamble stripping, the four validation
checks and the retry policy. The templates exist already; what is missing is the response handling,
and that is where a refusal or a chatty preamble would otherwise become a large delta and manufacture
a false positive.

---

## 2026-08-15 (third) — M5: the LLM layer

**Goal.** Build the provider seam, the cache, the ledger and the runner, so that every later
milestone can be developed and tested without an API key.

**Done.**
- `src/mmlsa/llm/base.py`: `LLMRequest`, `LLMResponse`, the `LLMProvider` protocol, and the error
  taxonomy the runner reasons about (transient, permanent, cache miss).
- `cache.py`: content-addressed store, three modes (`live`, `replay`, `refresh`), atomic writes.
- `ledger.py`: append-only `calls.jsonl` with the full rendered prompt and response, a schema
  validator, and a summarizer.
- `runner.py`: bounded-concurrency execution, a token-bucket rate limiter for both the request and
  the token budget, `tenacity` retries with exponential backoff and full jitter, and deterministic
  result ordering by `(creation_id, chunk_index)`.
- `providers/`: `FakeProvider`, `ReplayProvider`, and a registry. The three live backends are
  deliberately absent until M9 and fail with a message naming that milestone.
- CLI: `mmlsa cache stats` and `mmlsa cache verify`.

**Verified.**
- `pytest -q`: **383 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean.
- Coverage on `src/mmlsa/llm/`: **97 per cent**.
- All six M5 acceptance criteria, individually:
  the contract suite passes for both providers; the same request twice issues one provider call;
  bumping `prompt_schema_version` forces a new call; `replay` mode raises on a miss; every ledger
  line validates and cache hits are logged too; and a run killed after 17 of 40 calls, restarted
  with the same run id, issues exactly 23, with a third invocation issuing none.

**Decided.**
- `prompt_schema_version` lives on the request, not in global configuration (`DECISIONS.md` I21), so
  editing one template invalidates only that template's entries rather than the whole cache.
- The cache key excludes `tag` (`DECISIONS.md` I22). The tag says what a call is for, not what was
  asked, and including it would charge twice for one answer.
- A cache write that loses a race is a success, not an error (`DECISIONS.md` I20).

**Surprised by.** Two things.

1. **Concurrency plus content addressing produces a genuine write race, and Windows fails it.**
   Identical prompts give identical keys by design — the same passage can occur in two creations,
   and every retry re-enters the same key — so parallel workers collide on one entry. The loser of
   the rename gets a `PermissionError`. Found by the ordering test, not in production, because that
   test happened to build jobs whose prompts did not vary by creation. The fix is small: if the
   destination exists afterwards, the write succeeded. The near miss is the interesting part — had
   the test used realistic prompts, this would have surfaced during the first wide run instead.

2. **How much of the design is load-bearing for resumability, and how little of it is code.** There
   is no checkpoint mechanism to test. Resume falls out entirely of consulting the cache before each
   call, which is why `docs/DECISIONS.md` I1 calls it the highest-leverage decision in the codebase.
   The resume tests are the only evidence that the property actually holds, so they are written
   against behaviour (call counts) rather than against implementation.

**Next.** M6, Step 1 profile extraction: token estimation, deterministic bin packing of whole
creations, `k` extraction calls and the merge call. Note that the corpus measures 1.065 million
words, so the multi-call path is the normal one, exactly as `docs/DECISIONS.md` I3 anticipated.

---

## 2026-08-15 (second half) — M2: the corpus

**Goal.** Assemble the 49-creation corpus and the three auxiliary sets, and make their integrity
checkable by a command.

**Done.**
- `data/corpus_sources.yaml`: all 49 creations with Gutenberg identifiers and the paper's own title
  for each, plus a 9-text noise pool, a 7-text held-out set and 3 mixture sources.
- `src/mmlsa/corpus/`: `gutenberg.py` (fetch, strict boilerplate stripping), `normalize.py` (ingest
  normalization and front-matter removal), `loader.py` (sources, disjointness, fetch, load),
  `manifest.py` (build and verify).
- CLI: `mmlsa corpus fetch` and `mmlsa corpus verify`.
- The 49 normalized creations and `data/manifest.json` are committed. Raw downloads are cached under
  `data/_raw/`, which is git-ignored.
- Tests: `test_normalization.py`, `test_manifest_verify.py`, `test_corpus_integrity.py`,
  `test_set_disjointness.py`.

**Verified.**
- `python -m mmlsa corpus verify`: **70 checks passed**, no warnings.
- 49 creations, **1,065,092 words**.
- `pytest -q`: **291 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean.
- Milestone M3's two deferred corpus-wide properties now pass over the real texts: the full-coverage
  round trip at P = 200, 400 and 600, and `delta(x, x) == 0` over all 2,600-odd chunks, with zero
  degenerate chunks. M3 is closed.

**Decided.**
- **Which Gutenberg edition family.** The paper gives titles only. The 1500 series was reconstructed
  as the source because it is the only one containing every unusual entry in the paper's list
  (Pericles, The Rape of Lucrece, The Two Noble Kinsmen, Sir Thomas More, Locrine, Mucedorus). Where
  Gutenberg holds a duplicate, the entry matching the series' modernized format was taken, so an
  original-spelling quarto is not mixed into a modernized corpus. Raised as Q12.
- **Locrine and Mucedorus** are concatenated into one creation to preserve N = 49, matching the
  paper. Raised as Q13.
- **Noise texts must be creation-scale**, 10,000 to 60,000 words, enforced by a test. A noise text is
  added to the corpus *before* profile extraction, so The Faerie Queene at 472,000 words would have
  been a third of the corpus and would have rewritten the profile rather than perturbed it.

**Surprised by.** Four things, and the plan predicted the shape of all of them when it said this was
the milestone most likely to be underestimated.

1. **The paper has no Gutenberg identifiers at all.** `docs/DATA.md` assumed they were in it. They
   are not; it says only that the texts come from Gutenberg. The whole edition mapping had to be
   reconstructed and is now a documented assumption rather than a transcription.

2. **Two identifiers recalled from memory were simply wrong**, and checking every one against the
   Gutenberg catalogue caught both: 18268 is a Bliss Carman poetry collection, not Dekker's
   *Shoemaker's Holiday*, and 60287 is a Finnish novel, not *Gorboduc*. Neither would have failed
   loudly. They would have quietly become "foreign text" in a robustness experiment.

3. **Eyeballing the normalized files by hand found a real bug**, which is exactly what `docs/PLAN.md`
   said to budget time for. The scene lists and cast lists were surviving, because the first
   "ACT I" in these files is a contents entry rather than the play, and the rule was anchoring on
   it. Rewritten to anchor on the cast list, which sits between the contents and the body. It fires
   on 46 of 49; the three it skips are the poems, which have neither. 14,395 words of apparatus
   removed. **No test caught this** — `corpus verify` passed the whole time. Reading the files did.

4. **The corpus is 1.065 million words against a documented estimate of 0.9 to 1.0 million.**
   Measured rather than assumed or tolerated: speaker prefixes are 6.7 percent of it, stage
   directions 2.8, headings 0.6, and the spoken text is 956,416 words, inside the estimate. The
   sanity band was corrected to bound the quantity actually being measured. Recorded as `RESULTS.md`
   F-00, which also gives Q4 the number it previously lacked.

**Next.** M5: the provider protocol, cache, ledger and runner. Read `docs/ARCHITECTURE.md` section 4
first. `FakeProvider` has to produce non-trivial deterministic rewrites, or every downstream delta is
zero and the integration tests prove nothing.

---

## 2026-08-15 — Phase B kickoff: repository, environment, continuity docs

**Goal.** Turn the approved Phase A specification into a working repository and start the build.

**Done.**
- Cloned `eliranmeleh/Multi-Modal-LLM-Style-Analysis` (previously held only `book/` and
  `presentation/`) and copied the Phase B specification kit into it: `CLAUDE.md`, `docs/` (13 files),
  `configs/` (7 files), `pyproject.toml`, `.github/workflows/ci.yml`, `.gitignore`, `.env.example`,
  `LICENSE`, `CITATION.cff`, `CONTRIBUTING.md`.
- Added the continuity documents: `docs/STATUS.md` (live board), this file, and `docs/MEETINGS.md`.
- Provisioned Python 3.11 through `uv` into `.venv`.
- Created the package skeleton `src/mmlsa/` with the Typer entry point.

- Built **M0** (package skeleton, Typer CLI, test layout, CI fixes), **M1** (config model, `extends`
  resolution, config hashing, four-layer precedence, structured logging), **M3** (chunking, the
  function-word tokenizer, FWED with the private-use-area sequence Levenshtein, the distance
  registry, the versioned 127-entry word list) and **M4** (aggregation, exact Otsu, the `skimage`
  cross-check, a Gaussian-mixture fallback, bimodality diagnostics, `scores.csv`, `threshold.json`
  and the three figures).
- 227 tests, written before or alongside each implementation.

**Verified.**
- `docs/SPEC.md` checked line by line against the approved book
  (`Project_Book_Phase_A.docx`, 17 July 2026): sections 4.1, 4.3, 4.6, 4.7, 4.8, 4.9, and the two
  prompt templates in 5.2. No drift found. The spec is a faithful transcription and remains the
  contract.
- `ruff check .`, `ruff format --check .` and `mypy src` all clean.
- `pytest -q`: 227 passed. Coverage 91 percent overall; on the modules where a bug is silent,
  `tokenize` and `score` at 100, `chunking` 95, `fwed` 95, `classify` 92.
- `python -m mmlsa config validate`: all seven shipped configs resolve, including the two-level
  `extends` chains.
- `python -m mmlsa run --config configs/poc.yaml --dry-run` resolves and prints the plan without
  touching data.

**Decided.**
- Python 3.11 is provisioned with `uv` rather than relaxing `requires-python` to admit the machine's
  system 3.12. The book's tools table names 3.11 and examiners read it, so the environment matches the
  document instead of the document being edited to match the machine. Recorded as `DECISIONS.md` I19.
- Provider order: Gemini first, on the free tier, because it has the largest context window (the
  profile step packs whole creations) and the book names it first among the candidates. `llm.provider`
  is one config key, so the eventual model-choice decision at M9 costs nothing to change.
- Override keys are matched against the model's field names case-insensitively (`DECISIONS.md` I18).
  Found by a failing test: `MMLSA_RUN__M` was being lowercased to `run.m`, and the two specified keys
  that are single uppercase letters, `chunking.P` and `run.M`, were therefore unreachable from the
  environment. Unknown override keys now raise instead of being ignored.
- The book's visual bimodality check is also computed numerically (`DECISIONS.md` I17), as Otsu's
  separability and the gap at the split in standard deviations. Both are config keys, not constants.

**Surprised by.** Three things, all recorded rather than patched over.

1. **The function-word list has no wh-adverbs.** `when`, `where`, `why`, `how` are absent from the
   v1 composition in `docs/DATA.md` section 5.1, although `while`, `since` and `then` are present.
   The documentation's own worked example in section 5.3 assumed `when` was in the list and gave
   `3/7 = 0.4286`; the list as specified gives `3/6 = 0.5`. The example was corrected to match the
   list, because 5.1 is the normative text and the list is versioned for exactly this reason.
   Raised as `OPEN_QUESTIONS.md` Q10. **This must be settled before M10** — changing the list changes
   every delta ever computed.

2. **The Otsu cross-check cannot compare the two thresholds numerically**, which is what the spec
   asks for. Both implementations pick the same split but report `tau` at different points inside the
   gap: the exact form at the midpoint, `skimage` at the centre of the last bin below the split. The
   difference is half the gap width, so a *cleaner* separation looks like a *worse* disagreement. The
   check now compares which gap the two split at. Raised as `OPEN_QUESTIONS.md` Q11.

3. **The binned threshold really does move a label.** On a clean two-cluster example, `skimage`
   returns a value fractionally below the largest lower-class score, which pushes that creation into
   the suspicious set. This is direct empirical support for `DECISIONS.md` I2 and is worth a sentence
   in the Phase B report: with 49 points, `nbins` is not a harmless default.

**Next.** M2. Extract the 49 titles and Gutenberg identifiers from `fqaf009.pdf` into
`data/corpus_sources.yaml`, then fetch, normalize and build the manifest. Then close out M3 by
re-running its two corpus-wide properties over the real texts.
