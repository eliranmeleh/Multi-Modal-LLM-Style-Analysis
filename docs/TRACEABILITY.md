# TRACEABILITY

Every requirement and every method step in the approved Phase A book, mapped to the module that
implements it and the test that proves it.

Two uses. During development it answers "where does this live" without a search. At submission it is the
artifact that shows the implementation actually covers the specification, which is exactly what the
Phase B report and the defence are asked to demonstrate.

Keep it current. A stale traceability matrix is worse than none, because it asserts coverage that is
not there.

---

## Method steps (book section 4.6)

| Step | Book | Module | Primary tests |
|------|------|--------|---------------|
| 1. Style-profile extraction | 4.6.1 Step 1 | `pipeline/profile.py` | `unit/test_prompt_neutrality.py`, `integration/test_pipeline_end_to_end.py` |
| 2. Full-text chunking | 4.6.1 Step 2 | `chunking.py` | `unit/test_chunking.py` |
| 3. LLM rewriting | 4.6.1 Step 3 | `pipeline/rewrite.py` | `unit/test_rewrite_validation.py` |
| 4. Function-Word Edit Distance | 4.6.1 Step 4, 4.6.3 | `distance/fwed.py`, `distance/tokenize.py` | `unit/test_fwed.py`, `unit/test_tokenize.py`, `unit/test_function_words.py` |
| 5. Per-creation aggregation | 4.6.1 Step 5 | `pipeline/score.py` | `unit/test_aggregate.py` |
| 6. Threshold classification | 4.6.1 Step 6 | `pipeline/classify.py` | `unit/test_otsu.py` |
| `M` independent runs, noise injection | 4.6.1, 4.9 | `pipeline/orchestrator.py`, `pipeline/noise.py` | `unit/test_noise_selection.py`, `integration/test_pipeline_end_to_end.py` |
| Pseudocode (Figure 2) | 4.6.2 | `pipeline/orchestrator.py` | `integration/test_pipeline_end_to_end.py` |
| Optional purification | 4.6.1, 4.3 Stage 4 | `experiments/purification.py` | deferred, Phase B optional |

## Functional requirements (book section 4.1.1)

| # | Requirement | Module | Test |
|---|-------------|--------|------|
| F1 | Process the canonical 49-creation corpus from Project Gutenberg | `corpus/loader.py`, `corpus/gutenberg.py` | `data/test_corpus_integrity.py` |
| F2 | Extract a generic style profile from the full corpus, whole creations, no Shakespeare cue, split across calls if needed | `pipeline/profile.py` | `unit/test_prompt_neutrality.py` |
| F3 | Partition every creation into consecutive same-size chunks, full coverage, no sampling | `chunking.py` | `unit/test_chunking.py` (round-trip property) |
| F4 | `M` independent runs, noise from run 2, non-cumulative, scores averaged | `pipeline/orchestrator.py`, `pipeline/noise.py` | `unit/test_noise_selection.py` |
| F5 | FWED with about 120 modern and Early Modern function words, symmetric normalization | `distance/fwed.py` | `unit/test_fwed.py` |
| F6 | Classify via Otsu on the averaged scores | `pipeline/classify.py` | `unit/test_otsu.py` |
| F7 | Optional purification bounded by `T_max` | `experiments/purification.py` | deferred |
| F8 | Control experiment, profile prompt versus generic prompt | `experiments/control.py` | `validation/`, F-06 in `RESULTS.md` |
| F9 | Sorted scatter with threshold, labelled suspicious list, per-creation standard deviation | `reporting/plots.py`, `reporting/tables.py` | `unit/test_aggregate.py`, visual review |

## Non-functional requirements (book section 4.1.2)

These are the ones most easily claimed and least easily proven. Each has a mechanism, not a promise.

| # | Requirement | Mechanism | Enforced by |
|---|-------------|-----------|-------------|
| N1 | **Reproducibility.** Labels stable across the `M` runs for every non-borderline creation | Averaging over runs; per-creation standard deviation recorded; cache and replay mode | `RESULTS.md` F-03; `integration/test_resume.py` |
| N2 | **Generalizability.** Parameters expressed in terms of creation length; no code path hard-codes the author | Author name only in `config.corpus.author_label` and `data/` | `test_no_hardcoded_author.py` |
| N3 | **Interpretability.** Every per-creation score traceable back to its chunk deltas; output readable by non-technical readers | `DistanceResult.detail` stores the edit script (`you -> thou`); `deltas/run_i.csv` keeps every chunk | `unit/test_fwed.py`; report review |
| N4 | **Documentation.** All code, prompts, configuration and result files in a public repository | `src/mmlsa/prompts/*.txt`, `configs/`, committed run summaries | Repository contents |
| N5 | **Modularity.** The LLM provider configurable via a single setting | `LLMProvider` protocol; no concrete provider imported in `pipeline/` | `contract/test_provider_contract.py`; `integration` provider-swap test |
| N6 | **Auditability.** Every LLM call logged with prompt, response, model version and timestamp, so a run can be reproduced exactly | `llm/ledger.py` writes `calls.jsonl`; `llm/cache.py` content-addresses every call | `unit/test_ledger.py`, `unit/test_cache.py` |

## Success metrics (book section 4.8)

| # | Metric | Implementation | Recorded in |
|---|--------|----------------|-------------|
| 1 | Reproducibility of labels across runs | `reporting/tables.py` stability table | `RESULTS.md` F-03 |
| 2 | Profile contribution, paired t-test at `alpha = 0.05` | `experiments/control.py` | `RESULTS.md` F-06 |
| 3 | Agreement with consensus, at least 4 of 5 | `reporting/tables.py` against `data/consensus_cases.yaml` | `RESULTS.md` F-05 |

## Testing process (book section 4.9)

| Test | Implementation | Automated test |
|------|----------------|----------------|
| Reproducibility / calibration | `experiments/sensitivity.py` | `validation/test_calibration.py` |
| Synthetic mixture | `experiments/mixture.py` | `validation/test_mixture.py` |
| Held-out generalization | `experiments/heldout.py` | `validation/test_heldout.py` |
| Noise robustness (main proposal) | `pipeline/noise.py`, `experiments/sensitivity.py` | `validation/test_noise_robustness.py` |

The book states that each test is an automated suite so that future researchers can re-run the
verification with a single command. That command is `pytest tests/validation -q`.

## Research process (book section 4.3)

| Stage | Config | Milestone | Result |
|-------|--------|-----------|--------|
| 1. Proof of concept | `configs/poc.yaml` | M10 | `RESULTS.md` F-02 |
| 2. Reproducibility and sensitivity | `configs/sensitivity.yaml` | M11 | F-03, F-04 |
| 3. Full corpus run | `configs/full.yaml` | M12 | F-05 |
| 4. Optional refinement | `configs/purification.yaml` | M17 | conditional |
| 5. Control experiment and comparison | `configs/control.yaml` | M13 | F-06 |

## Risks (book section 4.10)

| Risk | Mitigation in code | Where |
|------|--------------------|-------|
| LLM memorization inflates accuracy | Control experiment; held-out corpus fallback | `experiments/control.py`, `experiments/heldout.py` |
| Run-to-run LLM variance | Averaging over `M` runs; pinned model version; logged seeds | `pipeline/orchestrator.py`, `manifest.json` |
| Distribution not bimodal | Bimodality diagnostic; Gaussian-mixture fallback | `pipeline/classify.py` |
| Contaminated profile (single round) | Stated limitation; optional Phase-B purification | `docs/SPEC.md` section 8 |
| Disagreement with prior results | Reported as a finding, both directions | `reporting/tables.py`, `RESULTS.md` F-05 |

## Tools table (book section 4.5)

Every tool named in the approved book appears in `pyproject.toml`. If a tool listed there ends up unused,
say so in the Phase B report rather than leaving a silent discrepancy between the book and the code.

| Book entry | Where used |
|------------|------------|
| Python 3.11 | `pyproject.toml` `requires-python` |
| Pipeline LLM (Gemini 2.5 / GPT-class / Claude) | `llm/providers/` |
| python-Levenshtein | `distance/fwed.py` |
| scikit-image | `pipeline/classify.py`, Otsu cross-check |
| scikit-learn | `pipeline/classify.py` Gaussian-mixture fallback; comparison classifiers |
| NumPy / Pandas | throughout |
| Matplotlib / Seaborn | `reporting/plots.py` |
| Project Gutenberg | `corpus/gutenberg.py`, `data/corpus_sources.yaml` |
| Git / GitHub | repository, releases, CI |
