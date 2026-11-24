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

### F-00b. The corpus needs three profile-extraction calls, as the design assumed
**Date:** 2026-08-15. **Run id:** none (offline planning). **Milestone:** M6.

**Question.** `docs/DECISIONS.md` I3 designed the multi-call profile path on the premise that the
corpus does not fit one context window, expecting 2 to 4 calls. Is that true of the corpus we
actually assembled?

**Result.** 49 creations, 1,065,092 words, **1,437,851 estimated tokens** at 1.35 tokens per word.
Packing whole creations under a budget of 70 per cent of the window:

| Context window | Input budget | Calls (`k`) |
|---|---:|---:|
| 128,000 | 89,600 | 17 |
| 200,000 | 140,000 | 11 |
| 1,000,000 | 700,000 | **3** |
| 2,000,000 | 1,400,000 | 2 |

**Verdict.** Confirmed. At the million-token window of the leading candidate model, `k = 3`, inside
the predicted range. The merge call is therefore the normal path and not a rare fallback, which is
what `docs/OPEN_QUESTIONS.md` Q1 asks the supervisors to confirm.

**Surprising.** How sharply `k` rises below a million tokens: a 128k model would need 17 extraction
calls per run, so the profile would be assembled from 17 partial views and one merge. That is a real
argument for the large-window model at M9, independent of rewrite quality, and it is worth stating
in the model-choice decision rather than discovering during a run.

**Action.** Record `k` per run in the run artifacts, which Step 1 already does. Revisit if the model
chosen at M9 has a smaller window.

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

### F-09. The first real calls, and the model of record

**Milestone:** M9. **Status:** measured, partial. **Runs:** `compare-20260829T1200-s20260731`
(mini fixture), `compare-20260829T1212-s20260731` (mini fixture), `compare-20260829T1216-s20260731`
(five real creations).

The project's first live API calls, on 2026-08-29. Four things were measured that no offline test
could have produced.

**1. The model named in the configuration could not be called at all.** `gemini-2.5-flash` returns
`404 NOT_FOUND` — "no longer available to new users" — to any project created after its cutoff. It is
still listed by `models.list()`, so the catalogue is not the authority on what a key can reach. The
model of record is now `gemini-3.5-flash`, chosen on measured behaviour: see `DECISIONS.md` I28 and
`OPEN_QUESTIONS.md` Q16.

**2. The free tier allows 5 requests per minute per model**, reported as quota
`GenerateRequestsPerMinutePerProjectPerModel-FreeTier`. `configs/default.yaml` had asked for 240 at
concurrency 8, which is 48 times over, and the first run lost every rewrite to a 429 while the runner
retried into the same wall. Now 5 and 1. **This sets the scale of everything remaining:** a full-corpus
run of roughly 7,500 calls is about 25 hours of wall clock on the free tier, so M12 needs either a paid
tier or a schedule.

**3. On real text the rewrites are clean.** Ten chunks drawn round-robin from five creations, of which
seven produced usable rewrites and three were lost to 429s. No response needed cleaning, no preamble,
no code fence. Length ratios 0.9875 to 1.0425 against a permitted band of 0.60 to 1.60, and content
retention 0.89 to 0.99. Per-chunk deltas, after the correction in F-10:

| creation | chunk | delta | length ratio | content retention |
|---|---|---|---|---|
| a_yorkshire_tragedy | 11 | 0.0188 | 1.0000 | 0.949 |
| a_yorkshire_tragedy | 12 | 0.0888 | 1.0100 | 0.890 |
| king_henry_viii | 36 | 0.0265 | 0.9925 | 0.983 |
| king_henry_viii | 37 | 0.0227 | 1.0275 | 0.926 |
| the_life_of_timon_of_athens | 31 | — | 1.0425 | 0.988 |
| the_life_of_timon_of_athens | 32 | — | 1.0000 | 0.962 |
| the_tragedy_of_hamlet | 11 | 0.1399 | 0.9875 | 0.982 |

Mean delta over the five scored at the time, 0.0593, standard deviation 0.0534. **No weight should be
put on that number.** It is five chunks from five creations with no ground truth attached, and the two
Timon chunks were not scored in that run because of F-10. It establishes that the pipeline produces
plausible deltas end to end on real text, and nothing more.

**4. The profile comes back contrastive on real text too.** First written here as "the mini fixture
is not a rehearsal for real text", on the evidence that the fixture produced a contrastive profile and
three-version rewrites while real text produced clean ones. **That conclusion was wrong and is
corrected here**: the clean *rewrites* were real, but the *profiles* from the PoC corpus enumerate the
creations exactly as the fixture's did — 9 references to "Creation N" from `gemini-3.5-flash` and 12
from `gemini-3.1-flash-lite`, in run `compare-20260829T1247-s20260731`. For example: "Creation 1 uses
earthy, domestic, and often bawdy language ... Creation 2 and 4 utilize formal, courtly, and political
lexicon."

What the fixture changed was only whether Step 3 *acted* on the enumeration. It is the more serious
half of the problem, because it is silent: see `OPEN_QUESTIONS.md` Q15, now raised from a possibility
to an observation, and the threat-to-validity note below.

### F-11. Model comparison, the M9 acceptance artifact

**Milestone:** M9. **Status:** measured. **Run:** `compare-20260829T1247-s20260731`.
Ten identical chunks, drawn round-robin from the five PoC creations, seed 20260731.

| model | ok | mean delta | sd | length ratio | retention | needed cleaning | latency ms |
|---|---|---|---|---|---|---|---|
| `gemini-3.5-flash` | 7/10 | 0.0516 | 0.0460 | 1.009 | 0.954 | 0 | 2814 |
| `gemini-3.1-flash-lite` | 10/10 | 0.0323 | 0.0327 | 1.001 | 0.958 | 0 | 3098 |

The three chunks missing from the first row are the daily free-tier quota, not the model: see the note
on 20 requests per day in F-09.

**Output cleanliness.** Neither model needed cleaning on any chunk: no preamble, no code fence, no
commentary. Length ratios sit within 1 per cent of the original and content retention above 0.95 for
both. On this evidence the validation checks are not doing much work on real text — which is the
desired state, and the opposite of what the mini fixture suggested.

**Rewrite fidelity, read by hand.** Both models change function words and pronouns and leave content
words alone, which is precisely what the distance metric reads: "You speak like a green girl" becomes
"Thou speakest like a green girl", "teach you" becomes "teach thee", "yourself" becomes "thyself".

**They archaize rather than modernize.** This is worth stating because `docs/TESTING.md` section 7
names quiet modernization as the failure that would inflate every delta uniformly and look like a
working method. The observed direction is the opposite: the extracted profile describes archaic
second-person forms, and both models move the text toward that norm. The delta is therefore reading
distance from the corpus norm, which is the intent.

**Where they differ, and why it favours the smaller model.** `gemini-3.5-flash` reformats prose into
verse lines, **inserts words that were not there** ("yfaith"), and produces occasional broken grammar
("Ay, fashion you may call'st; go to"). `gemini-3.1-flash-lite` preserves the original layout and
stays grammatical ("Ay, fashion thou mayst call it"). Insertion is the more serious fault: it is
content the original did not have, and it is measured as style.

**Recommendation, for the supervisors' agreement.** `gemini-3.1-flash-lite` on this evidence, on three
grounds: it completed every chunk, it altered layout least, and it did not insert content. Its lower
mean delta (0.0323 against 0.0516) is **not** part of the argument — a lower delta is not a better
model, and reading it that way is the error `summary.md` warns against in its own header. Ten chunks
and one provider is thin evidence; a second provider should be measured before M12 if a key can be had.

### F-10. The refusal check discarded lines of dialogue, not refusals

**Milestone:** M9. **Status:** found and fixed. **Run:** `compare-20260829T1216-s20260731`.

Two of the ten chunks were rejected with reason `refusal` while returning full-length, in-style,
high-retention rewrites. The cause was a substring scan of the whole response against the refusal
markers, matching lines spoken by a character:

| chunk | marker matched | the line |
|---|---|---|
| 31 | `i will not` | `I will not kiss thee; then the rot returns` |
| 32 | `i cannot` | `Keep it, I cannot eat it.` |

Both phrases appear in the **original** passage as well as in the rewrite, so the check was not reading
the model's behaviour at all. The damage is not the lost chunk but the manner of the loss: chunks were
discarded **as a function of their content**, so the surviving sample of a creation was biased toward
passages whose characters happen not to refuse anything, and a creation with many such lines could
cross `rewrite.max_failed_fraction` and be marked unreliable for its subject matter.

Fixed by anchoring the scan to the opening of the response (`DECISIONS.md` I27,
`rewrite.validation.refusal_scan_chars`, default 200). Re-validating the two stored responses under the
fix accepts both, at content retention 0.988 and 0.962 and length ratios 1.0425 and 1.0000. Usable
chunks in that run go from 5 of 10 to 7 of 10.

**Worth stating plainly:** 612 offline tests did not catch this, and could not have. The suite's
pathological responses were all written by us, and we wrote refusals that look like refusals. It took
one real creation's dialogue to expose it. Regression tests now cover the three markers most likely to
appear in dramatic speech.

### F-12. The free tier caps input tokens per minute, and a retried profile call can exhaust it

**Milestone:** none; the Colab notebook asked for at meeting 1. **Status:** measured.
**Runs:** `runs/notebook/live/20261121-133013` (failed) and `runs/notebook/live/20261121-133338`
(succeeded), both from `notebooks/run_in_colab.ipynb` on 2026-11-21. Local, not committed.

The free tier limits input tokens as well as requests: **250,000 input tokens per minute per model**
for `gemini-3.1-flash-lite` (quota `GenerateContentInputTokensPerModelPerMinute-FreeTier`). A profile
request for *Macbeth* and *Henry VIII* is **69,883 input tokens**; the dry-run estimate was 62,801.

**The failure.** The service answered 503 three times in a row, and each retry resent the whole
request. The fourth attempt crossed the per-minute token quota, and the remaining attempts got 429.
With `llm.max_transient_retries` at 5 the profile failed, and the comparison had nothing to rewrite
against. The runner's token bucket did not prevent it: it estimates tokens from words plus
`max_output_tokens`, about 30 per cent under the real count here, against a 1,000,000 budget sized
for a paid tier.

**The fix, in the notebook only.** With `llm.tokens_per_minute=100000` and
`llm.max_transient_retries=8` (the notebook's `FREE_TIER` setting) the same command succeeded: the
profile on its first attempt, three rewrites on their second attempt after a 503, 6 of 6 rewrites
usable, mean delta 0.0867 (sd 0.0453), 7 calls. Run again, it issued no calls and reproduced every
delta exactly. `configs/default.yaml` is unchanged, because the runs of record are planned on a paid key.

**Three observations, none of them a result.**
1. The profile came back contrastive again ("Creation 1 ... Creation 2 ..."), as in F-09 and Q15.
2. The rewrites added Markdown emphasis to speaker names and stage directions (`**KING.**`,
   `[*King takes his seat*]`), which the August rewrites did not. FWED is unaffected, because
   asterisks and brackets are stripped as edge punctuation, but the layout changed.
3. The per-play means, *Macbeth* 0.0908 and *Henry VIII* 0.0826 on three passages each, say nothing
   at this size, and are shown in the notebook only as a preview of Step 5.

### F-13. The notebook runs in Colab end to end, and the remaining project is costed from measurement

**Milestone:** none; preparation for M10 to M14. **Status:** measured.
**Run:** the Colab notebook on the `notebook-review-fixes` branch, 2026-11-24, code at `4df8129`,
results kept in the Colab runtime for this run (Drive not mounted). Not committed.

**The notebook.** Every cell ran without error in Google Colab. Parts 1 to 3: 70 corpus checks, the
mini run's tau 0.0517 with `mini_beta` suspicious. Part 4 on `gemini-3.1-flash-lite`: 7 of 7 calls
answered after 11 responses of 503 (service busy) were retried; **76,853 input and 4,268 output
tokens**. The passage the notebook explains scored FWED 17 / 189 = 0.0899, equal to the pipeline's
recorded delta and to the value measured on 2026-11-21. Part 5 issued no calls and reproduced every
delta. The Part 6 dry run planned 972 calls.

**The profile is about 500 tokens.** The extracted profile was 316 words in the six structured
sections, so every rewrite prompt carries roughly 500 tokens of profile, not the 1,500 assumed in
`docs/reviews/2026-11-23-colab-notebook-and-cost.md`.

**The token model.** Input per rewrite call = 75 (template) + profile + `P` x 1.58 tokens; output =
`P` x 1.58 (a rewrite is as long as its passage, F-11); a profile call reads its corpus at 1.58
tokens per word (F-12). On this run it predicts 77,067 input and 4,291 output tokens against the
measured 76,853 and 4,268, within 0.5 per cent.

**Calls per experiment**, from `run --dry-run` with each experiment's settings (`P` = 400 and
`M` = 3 unless stated):

| Experiment | New calls, upper bound | Cost on `gemini-3.1-flash-lite` |
|---|---|---|
| M10 proof of concept | 972 | $1.43 |
| M11 stability and `P` sweep (`P` 200 to 600 at `M` = 5) | 9,181 | $10.84 |
| M12 full corpus | 8,270 (not 7,500) | $12.20 |
| M13 control, Mode A and B on 300 chunks | about 600 | $1.23 |
| M14 calibration, 100 chunks x 5 | 500 | $0.66 |
| M14 held-out, 7 texts | 1,836 | $2.41 |
| M14 noise test, no-noise runs 2 and 3 | 5,374 | $7.05 |
| M14 synthetic mixture | 540 to 8,259, by design | $1.15 to $11.28 |
| **Total** | **27,000 to 35,000** | **$37 to $47**, plus 5 per cent for retries |

Prices from Google's pricing page on 2026-11-24: `gemini-3.1-flash-lite` $0.25 input and $1.50
output per million tokens. The same work costs $56 to $72 on `gemini-3.5-flash-lite` and $98 to
$125 on `gemini-3.8-flash`, whose price doubles on 2027-01-01. Upper bounds: reuse through the
cache (M10's runs inside M11, M12's run 1 inside M13 Mode A) lowers them. M17, purification, is
optional and not counted; it could add up to five full runs.

**What the project's API key can do.** Read from Google AI Studio for the project `mmlsa-phase-b`:
**free tier, no billing set up.** On the free tier `gemini-3.1-flash-lite` and
`gemini-3.5-flash-lite` now allow **15 requests a minute, 250,000 input tokens a minute and 500
requests a day** each; every other text model allows 20 a day. Tier 1, once billing is set up,
allows about 4,000 a minute and 150,000 a day for the same model. A Google AI Pro subscription on
the same account does not change the API tier: its listed benefits contain no API or Cloud credit.

**Consequences.**
1. **M10 fits the free tier**: 972 calls is two days at 500 a day, and its profile requests (about
   160,000 tokens, up to 210,000 with an injected creation) fit under the per-minute token limit,
   narrowly: a retried profile call inside the same minute would not (F-12).
2. **The whole project does not**: 54 to 70 days at 500 a day, and the full corpus packs into three
   profile requests of about 560,000 tokens each, which exceed the free tier's 250,000 tokens per
   minute and cannot succeed there at all. `profile.context_budget_tokens` could pack smaller bins,
   but that changes `k`, a method parameter, so it needs the supervisors' agreement.
3. **`gemini-3.5-flash`, the provider default in `src/mmlsa/llm/providers/gemini.py`, is gone**:
   it is absent from the pricing page and from the project's model list. Any run that leaves
   `llm.model_id` null would fail. The notebook already passes `MODEL` (review N4).

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
| Uniform modernization inflating all deltas | **Checked at M9 and not observed.** Both models archaize toward the profile rather than modernize (F-11) | F-11 |
| **A contrastive profile flattening the signal** | **Observed at M9 on real text, both models** (F-09 item 4, Q15). A profile that describes each creation separately invites Step 3 to rewrite a chunk toward its own creation's style, which shrinks every delta | Q15; tested at M10 by whether the known cases separate |
| Genre effect confounding authorship (poems vs plays) | Genre-split scores in F-05 | |
| Run-to-run stochasticity | F-03 | |
