# OPEN QUESTIONS

Points where the approved specification is silent, ambiguous, or where implementation revealed something
the method did not anticipate. Each entry states the question, the interim behaviour implemented, and who
needs to resolve it.

**Rule:** never resolve one of these silently in code. Implement the interim behaviour, keep the entry
open, and raise it at the next supervisor meeting.

Status values: `open`, `raised`, `resolved`, `deferred to Phase B`.

---

## Q1. Consolidating multiple profile-extraction calls
**Status:** open. **Needs:** supervisors.

The book specifies that if the corpus does not fit the context window, extraction is split into multiple
calls each holding complete creations. It does not say what happens next. Measured corpus size is roughly
1.2 to 1.35 million tokens, so the split is the normal path, not a rare fallback, and two to four partial
profiles will be produced on every run.

**Interim behaviour:** one additional merge call consolidates the partial profiles into a single profile,
using a neutral prompt that forbids introducing unsupported observations. See `docs/PROMPTS.md` section 2.

**Alternatives if the supervisors prefer:** (a) concatenate the partial profiles into the rewrite prompt
without merging, which lengthens every rewrite prompt and risks contradictory instructions;
(b) rewrite each creation under the profile from the bin that contained it, which breaks the "one profile
per run" property. The merge call is recommended over both.

## Q2. Does the injected noise text get scored?
**Status:** open. **Needs:** supervisors. **Low stakes.**

The book injects a foreign creation into the corpus before profiling in runs 2 to `M`. It does not say
whether that text is also chunked, rewritten and scored.

**Interim behaviour:** it is scored and reported as a diagnostic, and it is excluded from the threshold
computation and from the reported suspicious set. It changes no specified quantity and provides free
evidence that the pipeline behaves as intended.

## Q3. Unweighted versus length-weighted chunk mean
**Status:** open. **Needs:** supervisors. **Could affect published numbers.**

The per-creation score is the unweighted mean of chunk deltas. A trailing chunk of, say, 30 words carries
the same weight as a full 400-word chunk while being far noisier. For a 2,100-word creation such as
*A Lover's Complaint*, one short trailing chunk is a fifth of the mean.

**Interim behaviour:** the specified unweighted mean is the headline number. A length-weighted mean is
computed and reported alongside as a sensitivity check.

**Recommendation:** keep the unweighted mean as specified. Report the sensitivity and let the data decide
whether it matters. If the two disagree on any label, raise it immediately.

## Q4. Handling of dramatis personae and speaker prefixes
**Status:** open. **Needs:** team decision, then record it. **Affects every number.**

Play texts contain speaker names, stage directions and a dramatis personae block. These are editorial
artifacts as much as authorial text, and they differ between Gutenberg editions.

**Interim behaviour:** keep the text as printed, including speaker prefixes and stage directions, applied
identically to every text, and record the choice in the manifest.

**Reasoning:** speaker prefixes are stylistically inert for function-word analysis, whereas selective
removal heuristics tend to behave inconsistently across texts and introduce a new error source. The one
real risk is that the LLM rewrites a stage direction oddly. Inspect a sample during M10 and revisit.

## Q5. Do the poems belong in the same distribution as the plays?
**Status:** open. **Needs:** supervisors.

The corpus mixes dramatic verse, narrative poems and sonnets. Genre affects function-word usage
independently of authorship, so a poem could score high for reasons that have nothing to do with who
wrote it. Note that *Venus and Adonis* and *A Lover's Complaint* appear among the prior study's flagged
set, which is consistent with a genre effect rather than an authorship effect.

**Interim behaviour:** treat all 49 uniformly, exactly as specified, and additionally report scores broken
down by genre so the effect is visible rather than hidden.

**This is a genuine methodological risk worth raising early.** It is also a strong Phase B discussion
point, because it applies equally to the prior study.

## Q6. What counts as "the model version" for pinning?
**Status:** open. **Needs:** team decision at M9.

Providers alias model names to changing snapshots. A run pinned to a floating alias is not reproducible
even in principle.

**Interim behaviour:** record both the requested `model_id` and whatever version string the provider
returns, and prefer explicitly dated snapshot identifiers wherever the provider offers them. If the
returned version changes mid-run, flag the run.

## Q7. Threshold stability under a changing corpus
**Status:** deferred to Phase B.

`tau` is computed from the 49 scores, so it moves if the corpus changes. This makes cross-corpus
comparison of absolute scores meaningless, though within-corpus classification is unaffected. Relevant
only if the generalization claim is demonstrated on a second author's corpus.

## Q8. Sample size for the control experiment
**Status:** open. **Needs:** team decision at M13.

The book does not fix how many chunks the control experiment covers. Too few and the paired t-test lacks
power; all of them doubles the run.

**Interim behaviour:** a stratified sample of roughly 300 chunks, drawn across creations proportionally to
chunk count with a fixed seed. Report the achieved power alongside the p-value.

## Q9. Reporting when Otsu and the visible gap disagree
**Status:** open.

The book requires a visual sanity check: `tau` should fall in a visible gap in the sorted scatter.
It does not define what to do when it does not.

**Interim behaviour:** compute a bimodality diagnostic, flag the run, produce the histogram, and report
the Gaussian-mixture threshold alongside. Do not silently substitute one for the other; report both and
say which was used and why.

## Q10. The function-word list has no wh-adverbs and no elided forms
**Status:** open. **Needs:** supervisors. **Affects every number, and is expensive to change later.**

Implementing the tokenizer surfaced two gaps in the v1 list specified in `docs/DATA.md` section 5.1.

**No wh-adverbs.** `when`, `where`, `why` and `how` are absent, although the neighbouring
subordinators `while`, `since`, `though` and `although` are present, and `then` is present. This is
visible in the documentation's own worked example (section 5.3), which shows `when` inside `FW(x)`
and arrives at `3/7 = 0.4286`. With the list actually specified, `when` is dropped, the sequences are
six long, and the same example gives `3/6 = 0.5`. The example was corrected to match the list; the
list was **not** changed to match the example, because section 5.1 is the normative text.

**No elided forms.** `'tis`, `th'`, `ne'er` and similar Early Modern elisions are not entries, so
they are dropped from every sequence. The tokenizer still preserves apostrophes, which matters
regardless: stripping them would turn `it's` into `its`, which *is* an entry, and would silently
count a contraction as a possessive pronoun.

**Interim behaviour:** the list is implemented exactly as section 5.1 specifies, 127 entries. Nothing
was added. The list is versioned precisely so that this decision can be revisited deliberately rather
than drifted into.

**What is at stake.** Function words are the whole measurement. Adding four wh-adverbs would change
every delta ever computed, so this has to be settled *before* the run of record, not after. Against
adding them: the list is meant to be a fixed instrument, not tuned. For adding them: their absence
looks like an oversight rather than a choice, and wh-adverbs are standard in stylometric function-word
lists from Mosteller and Wallace onward.

**Recommendation:** raise at the next meeting. If they are to be added, do it as `en_core_v2.txt`
before M10, and record the change in `docs/DECISIONS.md`.

## Q11. The Otsu cross-check cannot compare the two thresholds numerically
**Status:** open. **Needs:** nothing blocking; recorded so the report states it accurately.

`docs/SPEC.md` section 3, Step 6 says to run `skimage.filters.threshold_otsu` alongside the exact
form and to flag the run "if they disagree by more than `classify.otsu_agreement_tol` (default
0.005)". Implementing that revealed the comparison does not mean what it appears to.

The two implementations choose the **same split**. They report `tau` at different points inside the
gap:

- the exact form returns the midpoint, `(s_k* + s_k*+1) / 2`;
- `skimage` returns the centre of the last histogram bin below the split, which converges to just
  under `max(lower class)` as the bin count grows.

On a clean two-cluster example (eight scores near 0.05, five near 0.20) the exact form gives 0.1225
and `skimage` gives 0.0549. The difference is **half the gap width**, so the tolerance would fire
hardest on the best-separated data — exactly backwards. Comparing the induced partitions instead
does not work either: `skimage`'s value sits fractionally below the largest lower-class score, so
that one creation flips to suspicious on every run, by construction rather than by evidence.

**Interim behaviour:** agreement is judged on **which gap** the two methods split at. The run is
flagged when the `skimage` threshold falls outside the exact split's gap by more than
`classify.otsu_agreement_tol`, which is the specified key at its specified magnitude doing a job the
number can actually support. The raw difference, the gap offset and the partition comparison are all
recorded in `threshold.json` regardless, so nothing is hidden.

**Worth noting in the report:** this is direct empirical support for `docs/DECISIONS.md` I2. The
binned threshold does not merely differ cosmetically; on this example it moves a creation across the
boundary. With 49 points, `nbins` really is a hidden hyperparameter that can change a label.

## Q12. The reference paper gives titles, not Gutenberg identifiers
**Status:** open. **Needs:** supervisors, ideally by asking the authors. **Affects comparability.**

`docs/DATA.md` section 2 instructs us to take "the exact list of 49 titles and their Gutenberg
identifiers from the reference paper". The paper's Table 4 lists all 49 titles. It gives **no
identifiers**, only the statement that the texts come from Project Gutenberg.

This matters because Gutenberg holds four largely parallel Shakespeare series (the 1100s, 1500s,
1700s and 2200s) plus duplicates within them, and the editions differ in ways that change function
words directly: modernized against original spelling, `you` against `thou`.

**Interim behaviour.** The 1500 series was reconstructed as the source, on the evidence that it is the
only one containing every unusual member of the paper's list: Pericles, The Rape of Lucrece, The Two
Noble Kinsmen, Sir Thomas More, Locrine and Mucedorus. The other series are missing several of these.
It supplies 39 of the 49; the remaining ten have a single Gutenberg edition each. Within the series,
where Gutenberg holds a genuine duplicate, the entry whose format matches the rest of the series was
taken, so that one original-spelling quarto is not mixed into a modernized corpus. Every identifier
was checked against the Gutenberg catalogue, and the reasoning is written into
`data/corpus_sources.yaml`.

**Why this is a real risk.** Success metric 3 and the agreement report both compare our labels against
theirs. If they used a different edition family, some part of any disagreement is editorial rather than
methodological, and we would have no way to tell which.

**Recommendation.** Ask the supervisors, who are the paper's authors, for the exact identifiers or the
files themselves. This is a five-minute question that removes a permanent caveat from the report.

## Q13. Locrine and Mucedorus are one creation in the paper and two on Gutenberg
**Status:** open. **Needs:** supervisors. Follows from Q12.

The paper's Table 4 lists a single creation, "LOCRINE MUCEDORUS BY SHAKESPEARE". These are two
separate apocryphal plays, and Gutenberg holds them as two texts (1548 and 1545). Treating them
separately would give 50 creations, not the 49 the book and the paper both specify.

**Interim behaviour.** The two are concatenated into one creation, `locrine_mucedorus`, preserving
N = 49. It is the only text in the corpus assembled from more than one file, and the manifest records
both source identifiers.

**Why it is worth raising.** A creation that is really two plays by possibly different hands has a
mixed style by construction, so its per-creation mean is an average over two populations. It is also
noteworthy that this entry is one of the few the reference paper's own methods disagreed about: cluster
2 in their Table 4, but flagged by all three summarization methods in their Table 7. A merged text is a
plausible explanation for that instability, and saying so is a genuine observation about the prior work.

## Q14. `temperature = 0` is specified, and several current models reject the parameter
**Status:** open. **Needs:** supervisors, for the record. **Raised:** 2026-08-16, wiring the live providers.

`docs/SPEC.md` Step 3 and `docs/PROMPTS.md` section 4 both fix the generation parameters:
`temperature = 0`, model version pinned, no top-p or penalty tuning. That was the right instruction
when the book was written, and it is still the right intent.

It is no longer universally expressible. Several of the current frontier models — including the
Anthropic models this project would compare, and the OpenAI reasoning families — **reject** a
`temperature` parameter with a 400 rather than accepting and ignoring it. On those models a
spec-faithful request is a failed request, and the specified value cannot be transmitted at all.

**Interim behaviour.** Each provider's model table records whether the parameter is accepted. Where it
is, the specified value is sent unchanged. Where it is not, the request is made without it and the
ledger records `temperature_requested` alongside `temperature_sent: false`, so nobody reading
`calls.jsonl` can mistake "sampling was pinned" for "sampling was left at the provider's default".
The cache key is unaffected either way: it holds the temperature that was *asked for*, and whether it
can be sent is a function of the model identifier, which the key already contains.

**Why it matters, and why it is smaller than it looks.** The book already anticipates the underlying
problem: `docs/SPEC.md` section 8 notes that even at `temperature = 0` provider APIs are not bit-exact
reproducible, and prescribes the mitigation — average over `M` runs, pin the model version, log every
call. All three of those hold here. What changes is that on some models the determinism argument rests
entirely on that mitigation rather than partly on the parameter. The `M`-run standard deviations
measured at M11 are the evidence either way, and they will be measured per model.

**Recommendation.** Note it in the Phase B book as an implementation constraint discovered during
integration, and let the M9 comparison include run-to-run stability as one of its criteria. If a model
that accepts `temperature` proves as good at the rewrite task as one that does not, that is a reason to
prefer it, and M9 is where that would be visible.

---

## Resolved

*(Move entries here with the date and the resolution. Nothing resolved yet.)*
