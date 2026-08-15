# RESULTS

The running record of Phase B findings. **Fill this in as results arrive, not at the end.**

Two reasons this file exists. First, the Phase B book is largely written from it, so keeping it current
turns report writing from an archaeology exercise into an editing exercise. Second, a finding recorded
the day it happened is honest, and a finding reconstructed three months later quietly becomes the
finding you wish you had got.

**Rules.**
- Every number cites a `run_id`. No number is typed by hand; all are generated from run artifacts.
- The prediction is written **before** the run, not after.
- Negative results are recorded with the same prominence as positive ones. A method that fails a check
  and says so is worth more than one that quietly passes everything.

---

## Status summary

| Success metric | Target | Status | Evidence |
|----------------|--------|--------|----------|
| 1. Reproducibility | Labels stable across the `M` runs for every non-borderline creation, implying at least 40 of 49 | not measured | |
| 2. Profile contribution | Mode A delta significantly lower than Mode B, paired t-test at `alpha = 0.05` | not measured | |
| 3. Agreement with consensus | At least 4 of the 5 firmest cases classified correctly | not measured | |

| Validation check | Pass condition | Status | Evidence |
|------------------|----------------|--------|----------|
| Calibration | Delta variance small across repeated rewrites | not measured | |
| Synthetic mixture | Spliced creations flagged, delta peaks at splice positions | not measured | |
| Held-out generalization | Reserved unseen texts classified correctly | not measured | |
| Noise robustness | Authentic labels stable with and without injected noise | not measured | |

---

## Configuration of record

Filled in once the pipeline model is chosen at M9. Everything published should come from this
configuration unless explicitly noted.

| Item | Value |
|------|-------|
| Provider and model snapshot | |
| `P` | |
| `M` | |
| Distance metric | |
| Threshold method | |
| Seed | |
| Function-word list | |
| Package version / commit | |

---

## Findings

Use one block per finding. Copy the template.

### Template

> **F-nn. Short title**
> **Date:** · **Run id:** · **Milestone:**
> **Question:** what was being asked.
> **Prediction (written before the run):** what was expected.
> **Result:** the numbers.
> **Verdict:** against the stated pass condition.
> **Surprising:** what did not behave as expected.
> **Action:** what happens next because of this.

---

### F-00. The corpus is larger than the documented estimate, and the excess is editorial apparatus
**Date:** 2026-08-15. **Run id:** none (corpus build). **Milestone:** M2.

**Question.** `docs/DATA.md` section 7 estimates the corpus at 0.9 to 1.0 million words. The assembled
corpus measures **1,065,092**. Is the corpus wrong, or is the estimate measuring something else?

**Result.** Measured over all 49 normalized creations:

| Component | Words | Share |
|---|---:|---:|
| Speaker prefixes | 71,638 | 6.7% |
| Stage directions | 30,352 | 2.8% |
| Act and scene headings | 6,686 | 0.6% |
| **Retained apparatus, total** | **108,676** | **10.2%** |
| Spoken text | 956,416 | 89.8% |
| **Corpus total** | **1,065,092** | 100% |

**Verdict.** The corpus is right and the estimate was measuring spoken text. Removing the apparatus we
deliberately keep leaves 956,416 words, inside the documented 0.9 to 1.0 million. The sanity band in
`corpus/manifest.py` was corrected to bound the quantity actually being measured rather than being
relaxed until it passed.

**Surprising.** How much of a play is not dialogue: one word in ten. This is a real input to
`docs/OPEN_QUESTIONS.md` Q4, which until now had no number attached. Speaker prefixes are 6.7 percent
of every chunk's raw material, and they are proper nouns, so they contribute almost nothing to the
function-word sequence the metric actually reads. The decision to keep them is close to free for FWED,
but it is **not** free for the rewrite step, where those 108,676 words are sent to the model and paid
for, and where a model may rewrite a stage direction oddly.

**Action.** Inspect a sample of rewritten chunks containing stage directions at M10, as Q4 already
requires. If the model mangles them, revisit. No change now.

**Also recorded at M2:** front-matter stripping removes 14,395 words of scene lists and cast lists
across 46 of the 49 creations. The three untouched are the poems, which have neither. Per-creation
removal counts are in `data/manifest.json` under `normalization`.

---

### F-01. Candidate model comparison
**Milestone:** M9. **Status:** pending.

Ten identical chunks rewritten by each candidate model. Compare rewrite fidelity, output cleanliness,
run-to-run stability and latency. This is the evidence for the model choice that the approved book
defers to the proof of concept.

| Model | Content preserved | Style shifted | Clean output | Mean delta | Notes |
|-------|-------------------|---------------|--------------|------------|-------|

**Decision and reason:**

---

### F-02. Proof of concept separation
**Milestone:** M10. **Status:** pending.

**Prediction:** Macbeth and Hamlet score below Henry VIII, Timon of Athens and A Yorkshire Tragedy,
with no overlap.

| Creation | Expected | `score_mean` | `score_std` | Label |
|----------|----------|--------------|-------------|-------|

---

### F-03. Run-to-run stability
**Milestone:** M11. **Status:** pending.

Per-creation mean, standard deviation, coefficient of variation, and whether the label moved across
the `M` runs. Recommendation for `M`.

---

### F-04. Chunk-length sensitivity
**Milestone:** M11. **Status:** pending.

Labels as a function of `P` over 200, 300, 400, 500, 600, on the proof-of-concept subset.
Note in the writeup that the sweep runs on a subset, and why.

---

### F-05. Full corpus run
**Milestone:** M12. **Status:** pending.

All 49 creations, `tau`, the suspicious set, the sorted scatter, per-creation confidence.
Agreement table against the prior published findings, reporting **both** directions of disagreement.

---

### F-06. Control experiment
**Milestone:** M13. **Status:** pending.

Paired t-test on per-chunk deltas, Mode A versus Mode B. Report p-value, mean difference with a
confidence interval, Cohen's `d`, Wilcoxon signed-rank, achieved power, and sample size.

This is the finding that decides whether the method measures something real or reproduces what the
model already knows. Report the outcome plainly in either direction.

---

### F-07. Synthetic mixture
**Milestone:** M14. **Status:** pending.

The strongest evidence available, because it is the only check with true ground truth. Report both
whether the spliced creations were flagged and whether the per-chunk delta peaks coincide with the
known splice positions.

---

### F-08. Noise robustness
**Milestone:** M14. **Status:** pending.

With-noise versus without-noise variants compared. Also report where each injected foreign creation
landed relative to `tau`.

---

## Deviations from the specification

Anything that ended up differing from `docs/SPEC.md`, with the reason and the approval.
Empty is the expected state.

| Date | What changed | Why | Approved by |
|------|--------------|-----|-------------|

## Threats to validity

Carried into the final report. Start from the known limitations in `docs/SPEC.md` section 8, and add
anything discovered during implementation.

| Threat | Evidence for or against | How it is reported |
|--------|-------------------------|--------------------|
| Profile contamination in the single-round method | | Stated limitation |
| LLM memorization of the corpus | Control experiment (F-06) | |
| Uniform modernization inflating all deltas | Manual review after M9 | |
| Genre effect confounding authorship (poems vs plays) | Genre-split scores in F-05 | |
| Run-to-run stochasticity | F-03 | |
