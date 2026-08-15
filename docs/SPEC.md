# SPEC — Method Specification

**Status:** frozen. Derived from the approved Phase A project book, sections 4.1, 4.3, 4.6, 4.7, 4.8, 4.9.
**Authority:** if this document and the code disagree, this document wins.
**Change control:** any change here requires supervisor approval and a note in `docs/DECISIONS.md`.

Sections marked **[IMPL]** are implementation-level precision that the book leaves open. They are
consistent with the book, never in conflict with it. Each one is justified in `docs/DECISIONS.md`.

---

## 1. Problem and output

**Input:** a corpus `W` of `N` texts (the running case: the 49 creations attributed to Shakespeare,
sourced from Project Gutenberg).

**Output, per creation:**
- a continuous score in `[0, 1]` (the mean style distance),
- a binary label, `authentic` or `suspicious`,
- a confidence diagnostic (standard deviation of the score across the independent runs).

**Output, per corpus:**
- the threshold `tau`,
- the suspicious set,
- a sorted scatter plot of all `N` scores with `tau` marked.

The procedure is unsupervised, zero-shot with respect to the LLM, and uses no impostor texts and
no classifier training.

## 2. Parameters

| Symbol | Meaning | Pilot default | Range |
|--------|---------|---------------|-------|
| `P` | chunk length in words | 400 | 200 to 600 |
| `M` | number of independent runs | 3 | 3 to 5 |
| `T_max` | maximum purification iterations (**Phase B only, optional**) | 5 | n/a in the core method |
| `alpha` | significance level for the control experiment | 0.05 | fixed |

The core Phase A method is **single round**. There is no feedback loop. Iterative purification is an
optional Phase B extension, adopted only if the single-round threshold proves unstable.

## 3. The pipeline

Six steps. Steps 1 to 5 are executed `M` times as independent runs; Step 6 runs once on the averaged scores.

### Step 1 — Style-profile extraction

The LLM receives the **full text of every creation in the corpus** and describes the dominant style:
vocabulary preferences, pronoun usage, verb forms, sentence structure, punctuation, and any other
distinctive linguistic features.

Rules:
- The prompt **never mentions Shakespeare** or any author name, period, or dialect.
- Whole creations only. **No truncation and no sampling within a creation.**
- If the corpus does not fit the model's context window in one call, split across multiple calls,
  each holding complete creations.
- The profile is re-extracted independently in every run.

**[IMPL] Multi-call packing and merge.** The 49-creation corpus is roughly 0.9 to 1.0 million words,
about 1.2 to 1.35 million tokens, so it will **not** fit in a single call on current models. The
implementation path is therefore:

1. Estimate the token count of every creation.
2. Bin-pack whole creations into `k` calls under `profile.context_budget_tokens`
   (default: 70 percent of the model window, leaving room for the response).
   Packing is deterministic: creations sorted by id, first-fit-decreasing by token count,
   ties broken by id.
3. Issue `k` extraction calls, producing `k` partial profiles.
4. If `k > 1`, issue one **merge call** that consolidates the `k` partial profiles into a single
   profile. The merge prompt also never names an author.
5. Record `k`, the packing, every partial profile and the merged profile in the run artifacts.

Note that the packing is a property of the corpus and the model window, so it is identical across runs
unless a noise creation changes it. That is expected and is recorded per run.

**[IMPL] Profile representation.** The profile is stored as JSON with the keys
`vocabulary`, `pronouns`, `verb_forms`, `sentence_structure`, `punctuation`, `other`, each a string.
This mirrors the six bullets of the book's prompt exactly. Set `profile.structured_output: false`
to fall back to a single free-text field, which is the book's literal form.

**[IMPL] Noise injection.** In runs `2 .. M`, one different foreign creation (from outside the corpus)
is added to the corpus **before** profile extraction. Run 1 uses the plain corpus. Noise never
accumulates: run `i` contains exactly one foreign creation, not `i - 1` of them.

- The foreign creation participates in Step 1 only.
- It is **not** part of the classified set and **never** contributes to `tau`.
- It **is** chunked, rewritten and scored as a diagnostic, reported separately. A correctly working
  pipeline should place it above `tau`.
- Selection is deterministic: the noise pool is sorted by id and consumed in order, offset by the run seed.

### Step 2 — Full-text chunking

Each creation is partitioned into **consecutive, non-overlapping** chunks of `P` words.
Full coverage: every word of every creation appears in exactly one chunk. No sampling.
The last chunk of a creation may be shorter than `P`.

**[IMPL] Word definition.** A word is a maximal run of non-whitespace characters after the
normalization in `docs/DATA.md` section 4. Chunk boundaries fall between words and never inside one.
Chunk `j` of creation `w` covers word indices `[j*P, min((j+1)*P, L_w))`.

**[IMPL] Short trailing chunks.** The spec says the last chunk may be shorter, so it is **kept as is**
and **not** merged into the previous chunk. A trailing chunk of very few words produces a noisy delta.
Record `n_words` per chunk so that a length-weighted aggregation can be reported as a sensitivity
check alongside the specified unweighted mean. The unweighted mean remains the headline number.

### Step 3 — LLM rewriting

Within a single run, each chunk is rewritten **once** under that run's profile, with instructions to
preserve content and change only stylistic features. Across the `M` runs each chunk therefore receives
`M` rewrites, each paired with an independent profile.

Generation parameters: `temperature = 0`, model version pinned, no top-p or penalty tuning.

**[IMPL] Response validation.** A rewrite is accepted only if all of the following hold. Thresholds
are config keys under `rewrite.validation`.

| Check | Default | On failure |
|-------|---------|------------|
| Non-empty after preamble stripping | required | retry |
| No refusal marker ("I cannot", "I'm sorry", "As an AI") | required | retry |
| Word-count ratio `len(rewrite) / len(original)` | in `[0.60, 1.60]` | retry |
| Content-word retention (overlap coefficient over non-function word types) | `>= 0.50` | retry |

Retries use the same prompt with an appended clarification, up to `rewrite.max_retries` (default 2).
A chunk that still fails is marked `status: "failed"`, **excluded from the creation mean**, and counted.
If more than `rewrite.max_failed_fraction` (default 0.02) of a creation's chunks fail, the creation is
flagged in the report and its score is marked unreliable.

A rewrite identical to the original is **valid**, not an error. It yields `delta = 0`.

**[IMPL] Preamble stripping.** Remove a leading conversational line matching
`^\s*(here(?:\s+is|\s?['’]s)|sure|certainly|rewritten|rewrite|below is)[^\n]*:\s*\n` (case-insensitive)
and remove enclosing Markdown code fences. Everything else is preserved verbatim, including line breaks.

*Corrected 2026-08-15.* This pattern previously read `here (is|'s)`, with a space before the group,
which matches "here 's" but not the contraction "here's" — the commoner of the two openings. An
unstripped preamble does not fail: it is measured as part of the passage and inflates that chunk's
delta. See `docs/DECISIONS.md` I23.

### Step 4 — Style distance

The distance developed with the method is the **Function-Word Edit Distance (FWED)**.

Let `FW(x)` be the ordered sequence of function words extracted from text `x`. For an original chunk `c`
and its rewrite `r`:

```
delta(c, r) = lev( FW(c), FW(r) ) / max( |FW(c)| , |FW(r)| )
```

where `lev` is the Levenshtein edit distance between two **sequences of tokens** (not characters) and
`|.|` is sequence length. The metric lies in `[0, 1]`: 0 when the two function-word sequences are
identical, 1 when they share nothing.

Properties that must hold and are unit-tested:
- `delta(x, x) == 0`
- `delta(c, r) == delta(r, c)` (symmetric, because the normalizer is symmetric)
- `0 <= delta <= 1`
- Edge case: if `|FW(c)| == 0 and |FW(r)| == 0`, define `delta = 0` and record the chunk as
  `degenerate: true`.

FWED is **one of a family** of candidate distances. The distance is selected through a registry so that
alternatives can be swapped without touching the pipeline:
- `fwed`: function-word edit distance (default, developed with the method),
- `fw_freq_cosine` / `fw_freq_manhattan`: order-insensitive frequency-vector distance over the same
  word set, related to Burrows's Delta,
- `signal`: a distance in the spirit of the prior study.

Phase B compares them empirically and reports which separates best. Whether to select one or combine
several is an open empirical question and is **not** decided here.

**[IMPL] Function-word extraction.** Defined precisely in `docs/DATA.md` section 5. Summary: normalize,
lowercase, tokenize, keep only tokens present in the versioned function-word list, preserve order.

**[IMPL] Sequence Levenshtein with `python-Levenshtein`.** That library operates on strings. Map each
distinct function word in the list to a unique Unicode code point in a private use area, encode both
sequences as strings, and compute the string distance. The result is exactly the sequence-level
distance because the mapping is injective. A pure-Python dynamic-programming implementation is kept in
the test suite as a cross-check on random inputs.

### Step 5 — Per-creation aggregation

Within run `i`, the score of creation `w` is the mean chunk delta:

```
s_i(w) = (1 / |chunks(w)|) * sum over c in chunks(w) of delta( c, r_i(c) )
```

Across the `M` runs, the final score is the mean of the per-run scores:

```
score(w) = (1 / M) * sum over i = 1..M of s_i(w)
```

The **standard deviation** of the `M` per-run scores is recorded as a per-creation confidence
diagnostic. Use the sample standard deviation (`ddof = 1`).

Failed chunks are excluded from the mean of that run. The chunk count used is recorded.

### Step 6 — Threshold classification

The `N` averaged scores are sorted and a parameter-free one-dimensional threshold `tau` separates
authentic from suspicious. **Otsu's method** is the classifier used in the developed method, one of
several compared in Phase B (for example a Gaussian-mixture split).

```
suspicious = { w in W : score(w) > tau }
```

Ties (`score(w) == tau`) classify as **authentic**, consistent with the strict inequality above.

**[IMPL] Exact Otsu on a small sample.** With only 49 points, histogram binning is a hidden
hyperparameter. Use the exact formulation instead: sort the scores `s_1 <= ... <= s_N`, and for each
split `k` in `1 .. N-1` compute

```
w0 = k / N,  w1 = 1 - w0
mu0 = mean(s_1 .. s_k),  mu1 = mean(s_{k+1} .. s_N)
sigma_b^2(k) = w0 * w1 * (mu0 - mu1)^2
```

Choose `k*` maximizing `sigma_b^2`, and set `tau = (s_{k*} + s_{k*+1}) / 2`. This is Otsu's criterion
with no binning parameter, and it converges to the binned result as the bin count grows.
`skimage.filters.threshold_otsu` is run alongside as a cross-check and both values are recorded.
If they disagree by more than `classify.otsu_agreement_tol` (default 0.005) the run is flagged.

**Visual sanity check.** The sorted scatter plot must show `tau` falling in a visible gap. Agreement
between the automatic threshold and the visible gap is evidence that the two-cluster structure is real.
If the distribution is not clearly bimodal, Otsu is fragile: inspect the histogram and fall back to a
Gaussian-mixture split or a manually justified threshold, and say so explicitly in the report.

**Borderline reporting.** Creations whose score lies within `classify.borderline_band` (default 0.01)
of `tau`, or whose across-run standard deviation crosses `tau`, are reported as a **third category**
in the writeup even though the classifier itself remains binary.

## 4. Optional: iterative purification (Phase B only)

Not part of the core method. Adopted only if the single-round threshold proves unstable.

```
for t = 1 .. T_max:
    profile  <- ExtractStyleProfile(authentic_set)
    scores   <- run Steps 2..5 over all creations
    tau      <- Threshold(scores)
    suspicious_t <- { w : scores[w] > tau }
    if suspicious_t == suspicious_{t-1}: break
    authentic_set <- W \ suspicious_t
```

Full reclassification each iteration; creations may move in either direction. No margin and no
monotonic refinement. Convergence is empirical, not guaranteed. If `T_max` is reached without
convergence, report the last iteration and note the instability.

Known risk, stated in the book: a wrong early call propagates. This is exactly why it is optional.

## 5. Reference pseudocode

Transcribed from Figure 2 of the approved book.

```
Input:  corpus W;  chunk length P;  number of independent runs M
Output: per-creation scores;  suspicious set;  threshold tau

for i <- 1 to M do                                  # M independent runs
    # main proposal: for i >= 2, add one different noise creation
    # (run 1: none; non-cumulative)
    profile_i <- ExtractStyleProfile(W)              # profile from the whole corpus
    for each creation w in W do
        chunks <- split w into consecutive same-size pieces      # full coverage
        for each chunk c in chunks do
            r    <- Rewrite(c, profile_i)
            d_c  <- StyleDistance(c, r)              # example: function-word edit distance
        score_i[w] <- mean(d_c over the chunks of w)

for each creation w in W do
    score[w] <- mean(score_i[w] for i = 1 .. M)      # average the M runs

tau        <- OtsuThreshold({ score[w] : w in W })
suspicious <- { w in W : score[w] > tau }
return score, suspicious, tau
```

## 6. Success metrics

Three criteria, all checked in Phase B. The project meets its goal if all three are satisfied.

1. **Reproducibility.** Classification labels are stable across the `M` independent runs for every
   non-borderline creation. The only creations permitted to vary are the borderline / mixed-authorship
   cases identified by scholarly consensus: Henry VIII, Pericles, Henry VI Parts I to III, Timon of Athens.
   Since that exempt set numbers at most six, meeting the criterion implies stable labels for at least
   40 of 49 creations (>= 80 percent). Any non-borderline creation whose label varies is flagged and
   reported with explicit uncertainty annotations.

2. **Profile contribution.** The mean delta computed with the explicit profile is statistically
   significantly lower than the mean delta computed with a generic "in <author>'s style" prompt,
   evaluated by paired t-test at `alpha = 0.05`. Pairing is **by chunk**: the same chunk scored under
   Mode A and Mode B. Report the p-value, the mean difference, Cohen's `d`, and a Wilcoxon signed-rank
   test as a non-parametric backup.

3. **Agreement with consensus.** On the pre-registered firmest-consensus set
   (Henry VIII / Fletcher, Henry VI Parts I, II and III / Marlowe, Timon of Athens / Middleton), the
   pipeline must correctly classify **at least four of these five** creations as suspicious.

## 7. Validation tests

Four checks, specified in book section 4.9 and slide 11. Implementation detail in `docs/EXPERIMENTS.md`.

| Test | Procedure | Passes if |
|------|-----------|-----------|
| Reproducibility / calibration | Rewrite a representative sample of chunks `M` times, all else constant. Measure the variance of the deltas. | Coefficient of variation is small on the large majority of test chunks; otherwise raise `M` and repeat. |
| Synthetic mixture | Splice known non-corpus passages into pure creations at known positions. | (a) the spliced creations are flagged suspicious, and (b) per-chunk deltas peak at the spliced positions. |
| Held-out generalization | Reserve confirmed in-corpus and known out-of-corpus texts before finalizing; run the finalized pipeline on them. | Correct classification on unseen data. |
| Noise robustness | One different foreign creation injected per run (runs 2..M), scores averaged. | Authentic labels stay stable. Phase B also evaluates the no-added-noise variant and compares. |

## 8. Known limitations, stated openly

These are in the approved book and must be carried into the Phase B report. Do not paper over them.

- **Profile contamination.** The profile is extracted from the full corpus, including creations that may
  not be authentic, which is exactly what the method is designed to detect. In the single-round method
  this is a known limitation, mitigated only by the assumption that most of the corpus is authentic.
- **LLM memorization.** Widely circulated texts are likely in every major model's training data, so a
  model may reproduce a memorized version instead of genuinely normalizing. The control experiment
  detects this; the fallback is a held-out non-canonical corpus.
- **Run-to-run stochasticity.** Even at `temperature = 0`, provider APIs are not bit-exact reproducible.
  Mitigated by averaging over `M` runs, pinning the model version, and logging every call.
- **Long-context rewrite fidelity.** Models paraphrase more as inputs lengthen. `P` is chosen to stay in
  the faithful range; the sensitivity sweep quantifies this.
- **Non-bimodal distribution.** Mixed-authorship creations may land near `tau`. If the distribution is
  not clearly bimodal, Otsu is fragile and the fallback applies.

## 9. Scale

At the pilot defaults, for the 49-creation corpus:

| Quantity | Estimate |
|----------|----------|
| Corpus size | roughly 0.9 to 1.0 million words |
| Chunks at `P = 400` | roughly 2,400 to 2,500 |
| Rewrite calls at `M = 3` | roughly 7,200 to 7,500 |
| Profile calls per run | `k + 1` where `k` is the number of packing bins (expect 2 to 4) |
| Control experiment | roughly doubles the rewrite calls on the sampled subset only |
| Wall clock at concurrency 8 | roughly 45 to 120 minutes for a full run |
| Re-run from cache | minutes, zero API calls |

Cost is not a project constraint. Feasibility is reported as scale, not currency.
