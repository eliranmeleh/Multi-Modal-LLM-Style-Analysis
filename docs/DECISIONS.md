# DECISIONS

Settled decisions and the reasoning behind them. **Do not relitigate an entry here without new evidence.**
Append new entries; never delete one. If a decision is reversed, add a superseding entry and mark the old
one.

Two categories:
- **[SPEC]** decided during Phase A with the supervisors. Changing one requires their approval.
- **[IMPL]** engineering decisions made for Phase B. Changing one requires only a new entry here.

---

## [SPEC] Settled in Phase A

| # | Decision | Reasoning |
|---|----------|-----------|
| S1 | **Single round, no feedback loop.** | A wrong early call would corrupt the re-extracted profile and propagate. Iterative purification is deferred to Phase B and adopted only if the single-round threshold proves unstable. |
| S2 | **`M` independent runs, scores averaged.** | Cancels the model's run-to-run variability. Averaging scores rather than voting on labels preserves where each creation sits on the distance axis. |
| S3 | **Noise injection in runs 2..M, one different foreign text per run, run 1 plain, non-cumulative.** | Tests that a single intruder cannot flip the authentic classification. The no-added-noise variant is evaluated in Phase B as a comparison. |
| S4 | **Full-coverage chunking, no sampling.** | Every word of every creation is scored. Removes sampling as a source of variance and as a reviewer objection. |
| S5 | **Whole creations in profile extraction, never truncated or sampled.** | An extra API call is cheaper than losing text integrity. |
| S6 | **FWED is the metric the method is developed with, not "the chosen metric".** | The whole classification depends on the distance, so it is presented as one of a family compared empirically in Phase B. Never describe it as primary or final in any deliverable. |
| S7 | **Otsu is one illustrated option, not the committed classifier.** | Same reasoning as S6. A Gaussian-mixture split is the named alternative. |
| S8 | **Parameters are symbols with pilot defaults, not fixed values.** | `P`, `M`, `T_max`, `alpha`. Concrete numbers appear only in the worked example and in config. |
| S9 | **Model-agnostic; the pipeline LLM is selected in the proof of concept** by measured rewrite fidelity and run-to-run stability. | Cost is not a project constraint. Candidates: Gemini 2.5, a GPT-class model, Claude. |
| S10 | **Prompts are neutral: no author name, no period, no dialect cue.** | This is what makes the method unsupervised and transferable. The sole exception is the control experiment's Mode B. |
| S11 | **Profile contamination is a stated limitation, not a solved problem.** | Reported honestly in Phase B. |
| S12 | **Python 3.11 and the toolchain named in the book.** | The examiners read the tools table. |

## [IMPL] Engineering decisions for Phase B

| # | Decision | Reasoning | Reversible |
|---|----------|-----------|------------|
| I1 | **Content-addressed cache in front of every LLM call, with three modes (`live`, `replay`, `refresh`).** | A full run is roughly 7,500 calls. This single mechanism delivers resumability, exact reproducibility, auditability and free re-runs. It is the highest-leverage decision in the codebase. | No, it is foundational |
| I2 | **Exact Otsu by enumerating the 48 candidate splits, rather than the binned histogram form.** | With 49 samples, `nbins` becomes a hidden hyperparameter that could move the threshold. The exact form is the same criterion with no free parameter. `skimage` is run alongside as a cross-check and both are recorded. | Yes |
| I3 | **Multi-call profile extraction plus one merge call.** | The corpus is roughly 1.2 to 1.35 million tokens and does not fit a one-million-token window, so the split path is the normal path, not a fallback. The book specifies the split and leaves the consolidation implicit. Flagged in `docs/OPEN_QUESTIONS.md` for supervisor confirmation. | Yes |
| I4 | **Profile stored as JSON with the six keys from the book's own prompt bullets.** | Makes profiles diffable across runs, makes merging tractable, and makes rewrite-prompt rendering deterministic. Config flag `profile.structured_output: false` restores the book's literal free-text form. | Yes |
| I5 | **Rewrite responses are validated (length ratio, content retention, refusal, emptiness) with bounded retries; unrecoverable chunks are excluded and counted.** | Without this, a refusal or a chatty preamble silently becomes a large delta and manufactures a false positive. The book does not cover response handling because it specifies method, not engineering. | Yes, thresholds are config |
| I6 | **Trailing short chunks are kept, not merged.** | The book says the last chunk may be shorter. Deviating would change the specified quantity. Length-weighted aggregation is reported as a sensitivity check only. | Yes |
| I7 | **The injected noise text is scored as a diagnostic but excluded from `tau` and from the reported set.** | Free evidence that the pipeline works: a foreign text should land above the threshold. Costs nothing to observe and changes no specified quantity. | Yes |
| I8 | **Sequence Levenshtein via injective private-use-area code point mapping, using `python-Levenshtein`.** | Keeps the library named in the book's tools table accurate while giving true token-sequence distance rather than character distance. Cross-checked against a pure-Python reference in tests. | Yes |
| I9 | **The author name lives in `config.corpus.author_label` and in `data/`, never in `src/`.** | Turns the generalizability requirement into something a test can enforce rather than a claim in prose. | No |
| I10 | **Tests never call a real API; CI holds no keys.** | Deterministic CI, and no accidental spend from a pull request. | No |
| I11 | **Typer CLI, one entry point, no loose scripts in the repository root.** | The repository is a graded artifact and is read by examiners. | Yes |
| I12 | **Run directories are immutable and keyed by config hash and seed.** | Prevents the classic failure of silently overwriting the result you are about to report. | No |
| I13 | **Deterministic bin packing (sorted by id, first-fit-decreasing, ties by id) for profile calls.** | Packing must not vary between runs, or profiles differ for reasons unrelated to the method. | Yes |
| I14 | **Large artifacts (`rewrites/`, `calls.jsonl`) are gzipped and attached to a release; summary artifacts are committed.** | Meets the commitment to publish results and logs without bloating the clone. | Yes |
| I15 | **Distance and classifier are behind registries from day one, but only `fwed` and `otsu_exact` are implemented until the comparison experiment is scheduled.** | The interface cost is small and Phase B needs the seam; the implementations are not needed yet. | Yes |
| I16 | **Configs inherit through an `extends` directive resolved by the loader, and only the flattened result is validated, hashed and snapshotted.** | Six experiment configs differ from the reference by a handful of keys each. Copying the full file six times guarantees they drift apart, and a drifted `chunking.P` invalidates a comparison without anyone noticing. Flattening before hashing keeps the run id a function of the effective values rather than of the inheritance path, and keeps a run reproducible from its snapshot alone. | Yes, at the cost of six duplicated files |
| I17 | **The book's visual bimodality check is also computed numerically**, as Otsu's separability (between-class over total variance) and the gap at the split measured in standard deviations. Failing either flags the run; neither is an error. | The book requires that `tau` fall in a visible gap and treats agreement between the automatic threshold and the visible gap as evidence that the two-cluster structure is real. A check that exists only as an instruction to look at a picture is one that gets skipped under deadline. Making it a recorded number means the report can state it rather than assert it. Thresholds are config keys, not constants. | Yes, thresholds are config |
| I18 | **Environment and `--set` override keys are matched against the model's field names case-insensitively.** | Two specified keys are single uppercase letters, `chunking.P` and `run.M`, because that is how the book names them. An override layer that lowercased its input would silently miss both, and a silently ignored override looks identical to a flag that did nothing. Unknown keys are rejected rather than ignored for the same reason. | Yes |
| I19 | **Python 3.11 is provisioned with `uv` rather than relaxing the version bound to admit a newer interpreter.** | The book's tools table names Python 3.11 and examiners read it. Matching the environment to the document is a one-line command; editing the document to match whatever interpreter happens to be installed is a change to an approved deliverable. | Yes |

## Explicitly rejected

| Idea | Why not |
|------|---------|
| Fusing several distance metrics into one score by default | A weak metric contaminates a strong one and creates false confidence. Whether to select or combine is an open empirical question for Phase B, deliberately left undecided. |
| A margin band or monotonic refinement in the classification | Rejected in Phase A. Averaging over runs already cushions chatter, and locking decisions taken on a contaminated profile is the risk being avoided. |
| Sampling passages instead of full coverage | Removed in Phase A. Full coverage eliminates sampling variance and an obvious reviewer objection. |
| Isolation Forest as the classifier | The suspicious class is roughly 30 percent of the corpus, not a rare-outlier population, so the Isolation Forest framing is misaligned. It stays available only as a cross-check against the prior study. |
| A web interface or dashboard | The customer-interface section was removed from the book on purpose. This is a research pipeline. |
| Fine-tuning or training any model | The entire claim is that the method is zero-shot and requires no training. |
