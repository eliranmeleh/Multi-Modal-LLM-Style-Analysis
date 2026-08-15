# EXPERIMENTS

The research protocol: the five stages from the approved book, each mapped to a command, a config, the
artifacts it produces, and the criterion that decides the outcome.

**Rule for every experiment:** write down the expected result **before** running it. An experiment whose
prediction is written afterwards proves nothing.

---

## Stage 1 — Proof of concept

**Book section 4.3, Stage 1. Milestone M10.**

Implement the pipeline end to end on a small subset chosen to include a known mixed-authorship case
(*Henry VIII*, with Fletcher) and a confirmed pure case (*Macbeth*). Verify that the deltas separate the
known cases before scaling up.

```bash
python -m mmlsa run --config configs/poc.yaml --dry-run     # check the call count first
python -m mmlsa run --config configs/poc.yaml
python -m mmlsa report --run-id <run_id>
```

**Subset:** 4 to 6 creations. Suggested: Macbeth, Hamlet, Henry VIII, Timon of Athens, A Yorkshire Tragedy.
Two expected-authentic, three expected-suspicious, spanning play and apocrypha.

**Scale:** roughly 250 chunks times `M = 3`, so about 750 rewrite calls.

**Prediction to write down first:** the expected-authentic creations score lower than the
expected-suspicious ones, with no overlap.

**Outcome handling.** If separation appears, proceed. If it does not, **stop and diagnose before
scaling**. In order of likelihood: the model is modernizing spelling uniformly (check the manual review
in `docs/TESTING.md` section 7); the profile is vacuous; rewrites are failing validation at a high rate;
the function-word list is missing the forms that actually differ. A negative result here is cheap and
informative. Report it to the supervisors either way.

## Stage 2 — Reproducibility and sensitivity

**Book section 4.3, Stage 2. Milestone M11. Success metric 1.**

Two independent questions.

**(a) Run-to-run stability.** `M` independent runs on identical inputs. Report per creation: the `M`
scores, the mean, the sample standard deviation, the coefficient of variation, and whether the label
changed across runs.

**(b) Chunk-length sensitivity.** Sweep `P` over 200, 300, 400, 500, 600 and check that classification
holds across the range.

```bash
python -m mmlsa experiment sensitivity --config configs/sensitivity.yaml
```

**Note on cost:** each `P` value invalidates the rewrite cache, because the chunks themselves change.
The sweep therefore costs roughly five full runs on the chosen subset. Run it on the proof-of-concept
subset, not on all 49, and say so in the report.

**Passes if:** labels are stable across the `M` runs for every non-borderline creation, and stable across
the `P` range. The exempt borderline set is Henry VIII, Pericles, Henry VI Parts I to III, Timon of Athens.

**If it fails:** the book prescribes raising `M` and repeating. Record the coefficient-of-variation
distribution that motivated the increase.

## Stage 3 — Full corpus run

**Book section 4.3, Stage 3. Milestone M12.**

All 49 creations, single round, `M` runs, no purification.

```bash
python -m mmlsa run --config configs/full.yaml --dry-run
python -m mmlsa run --config configs/full.yaml
python -m mmlsa report --run-id <run_id>
```

**Scale:** roughly 2,500 chunks times `M = 3`, so about 7,500 rewrite calls, plus `M * (k + 1)` profile
calls. Roughly 45 to 120 minutes at concurrency 8.

**Artifacts:** `scores.csv`, `threshold.json`, `figures/sorted_scatter.png`, `figures/histogram.png`,
`figures/run_variance.png`, `noise_diagnostics.csv`, and an agreement table against the prior published
findings.

**Report both directions of disagreement.** Creations flagged here but not previously, and creations
previously flagged but not here. Disagreement is an acceptable outcome and is part of the contribution.
Do not tune anything to increase agreement: that would turn an independent cross-check into a fit.

## Stage 4 — Optional refinement (purification)

**Book section 4.3, Stage 4. Milestone M17. Phase B, optional.**

Run **only if** Stage 2 or Stage 3 shows the single-round threshold to be unstable.

```bash
python -m mmlsa experiment purification --config configs/purification.yaml
```

Bounded by `T_max`. Report the suspicious-set difference between consecutive iterations as evidence of
convergence, or the absence of it. If `T_max` is reached without convergence, report the last iteration
and state the instability plainly.

**Do not run this by default.** The book deliberately excludes it from the core method because a wrong
early call propagates.

## Stage 5 — Control experiment

**Book section 4.3, Stage 5. Milestone M13. Success metric 2.**

The experiment that decides whether the method is real or is riding on the model's memorized prior.

- **Mode A:** rewrite under the extracted profile.
- **Mode B:** rewrite under a generic "in `<author>`'s style" prompt.
- **Same chunks in both arms**, so the test is genuinely paired.

```bash
python -m mmlsa experiment control --config configs/control.yaml
```

**Sample:** roughly 300 chunks, stratified across creations proportionally to chunk count, fixed seed.
See `docs/OPEN_QUESTIONS.md` Q8.

**Statistics:** paired t-test on per-chunk deltas at `alpha = 0.05`; report the p-value, the mean
difference with a confidence interval, Cohen's `d`, and a Wilcoxon signed-rank test as a non-parametric
backup. Report the achieved power.

**Passes if:** Mode A delta is significantly **lower** than Mode B delta. That is the direction that
matters: the explicit profile should make the text need less rewriting than a generic instruction does.

**If it fails**, the honest reading is that the method is largely reproducing what the model already knows
about the author. The book's stated fallback is a held-out non-canonical corpus, where memorization
cannot help. Report the failure; do not bury it.

## Cross-cutting: the four validation checks

Book section 4.9. Implemented as an automated suite, milestone M14. Details in `docs/TESTING.md`
section 5.

```bash
pytest tests/validation -q
```

| Check | Command | Passes if |
|-------|---------|-----------|
| Calibration | `experiment calibration` | Delta variance across repeated rewrites is small on the large majority of sampled chunks. |
| Synthetic mixture | `experiment mixture` | Spliced texts are flagged, and per-chunk delta peaks match the known splice positions. |
| Held-out generalization | `experiment heldout` | The finalized pipeline classifies reserved unseen texts correctly. |
| Noise robustness | `experiment noise` | Authentic labels are stable between the with-noise and without-noise variants. |

The **synthetic mixture test is the strongest evidence the project can produce**, because it is the only
check with true ground truth: the non-authentic positions are known in advance. Give it real attention.
It also exercises the per-chunk resolution that motivates chunking in the first place, and it is the one
experiment that can demonstrate localization, which the classifier itself does not attempt.

## Optional: distance-metric comparison

Milestone M16. Score the **same recorded rewrites** with every registered metric. This requires no new
LLM calls, since the rewrites are already cached, which is another payoff of the caching layer.

Compare on separation quality, for example the between-class variance at the chosen threshold, the size of
the gap around `tau`, and label agreement with the consensus cases. Report which metric separates best.
Whether to select one or combine several is left open by the specification and is decided by this
experiment.

## Reporting standard

Every experiment writes into the run report:

1. The question, and the prediction written before the run.
2. The exact command, the config hash, the seed, the provider and the model version.
3. The measured result, with the numbers, not a summary adjective.
4. The verdict against the stated pass condition.
5. What was surprising, and what will be done about it.

Numbers that appear in the final Phase B book must be traceable to a committed run directory.
Never retype a number by hand: generate the tables.
