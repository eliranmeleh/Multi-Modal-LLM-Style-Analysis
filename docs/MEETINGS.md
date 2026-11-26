# MEETINGS

Supervisor meetings: the running agenda for the next one, and the record of past ones.

Phase A was steered by regular meetings with Dr. Renata Avros and Prof. Zeev Volkovich, and several
of the method's defining choices came out of them (the move from Isolation Forest to Otsu, symbolic
parameters rather than fixed numbers, multi-run averaging). Phase B should be steered the same way.

Two rules keep this file useful:

1. **The agenda is built from `docs/OPEN_QUESTIONS.md`, not from memory.** Anything that needs a
   supervisor decision belongs there first; this file is where those questions get scheduled.
2. **A decision taken in a meeting is written into `docs/DECISIONS.md` the same day**, with the
   meeting date as its provenance. This file records that it happened; `DECISIONS.md` records what
   was decided and is the file the code is checked against.

---

## Next meeting — agenda

**Date:** not yet scheduled.

**Show first:** the pipeline running in Google Colab, `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb`. The supervisors
have not seen the implementation yet; meeting 1 asked for it to start.

**Then the M10 pilot (item J).** The prediction failed, and the run's own files show why: the style
profile described only the first play in its input. This is the item that most needs their decision.

| # | Item | Source | Why it needs them |
|---|---|---|---|
| J | The M10 pilot: one extraction call over five plays returned a profile of A Yorkshire Tragedy alone, and every play was rewritten toward it. Proposal: smaller extraction bins, so the specified merge call keeps only what the plays share, tested on the PoC plays for about $1.40. Also the Henry VIII scenes by Fletcher, which changed less than Shakespeare's. | `docs/RESULTS.md` F-15; `docs/OPEN_QUESTIONS.md` Q18 | Changes `k`, which the specification sets; blocks M10. |
| K | Also from the pilot: run 1, with no injected noise creation, scored about half of runs 2 and 3 for every play. If one foreign play raises every delta, the noise step shifts all the scores. Proposal: once J is settled, the five PoC plays with noise off and on, about $1.40. | `docs/RESULTS.md` F-15; `docs/OPEN_QUESTIONS.md` Q19 | Bears on the noise injection of the main proposal, and on the variant without noise. |
| L | Control experiment (M13): a one-sided or a two-sided paired t-test. Interim: two-sided, both p-values reported. | `docs/OPEN_QUESTIONS.md` Q20; `docs/DECISIONS.md` I38 | Success metric 2 does not name the sides, and the choice must be fixed before the run. |
| N | Stage 2 (M11): is run-to-run stability measured with noise injection on or off? Interim: as configured, on. | `docs/OPEN_QUESTIONS.md` Q22; `docs/DECISIONS.md` I40 | "Identical inputs" and the noise of the main proposal pull against each other, and success metric 1 rests on it. |
| M | Validation checks (M14): the numbers behind "large majority" (0.9 of chunks with CV at most 0.15), "peak at the splice" (within one chunk), and "correct" held-out classification (every text). | `docs/OPEN_QUESTIONS.md` Q21; `docs/DECISIONS.md` I39 | The spec states the conditions in words; they must be fixed before any check is recorded. |
| A | Which distances and classifiers to compare, and how the signal-based distance is defined. | `docs/DECISIONS.md` S6, S7; `docs/PLAN.md` M16 | Sets the scope of the comparison experiment. |
| B | Model of record: `gemini-3.1-flash-lite`. | `docs/DECISIONS.md` I28; `docs/RESULTS.md` F-11 | Gemini 2.5 is closed to new projects. |
| C | The API budget, and what the college reimburses: Colab, the API, or both. | `docs/STATUS.md`, blocked list | Full-size runs need a paid key. |
| D | Reproduction by the peer examiner through replay of recorded answers, plus a small live rerun. | `README.md`, Reproducing a published run | Decides what the Reproducibility Guide promises. |
| E | Whether a second author's corpus is expected for the generalization goal. | Book section 2.3, goals | Scope. |
| F | One sentence in the extraction prompt requiring a single unified profile. | `docs/OPEN_QUESTIONS.md` Q15 | `docs/PROMPTS.md` is frozen. |
| G | *when, where, why, how* added to the function-word list as version 2. | `docs/OPEN_QUESTIONS.md` Q10 | Must be settled before any run of record. |
| H | Their exact Gutenberg editions; Locrine and Mucedorus kept as one creation. | `docs/OPEN_QUESTIONS.md` Q12, Q13 | Removes a caveat from the agreement table. |
| I | Meeting cadence: every two weeks is proposed. | | |

Carried over from before meeting 1, still unconfirmed:

| # | Item | Source | Why it needs them |
|---|---|---|---|
| 1 | The profile **merge call**. The corpus does not fit one context window, so extraction is split across `k` calls; the book specifies the split but leaves consolidation implicit. We add one merge call. | `docs/OPEN_QUESTIONS.md` Q1, `docs/DECISIONS.md` I3 | It is an addition to the specified method, however small. Better confirmed than assumed. |
| 2 | Scoring the **injected noise creation** as a diagnostic, excluded from `tau` and from the reported set. | `docs/OPEN_QUESTIONS.md` Q2, `docs/DECISIONS.md` I7 | Free evidence that the pipeline works; confirm it does not count as changing the method. |
| 3 | **Model choice** for the pipeline LLM. The book defers this to the proof of concept. Plan: compare candidates at M9 on ten identical chunks and decide on measured rewrite fidelity and stability. | `docs/PLAN.md` M9, `docs/DECISIONS.md` S9 | They may have a preference, or access to a model we do not. |
| 4 | **Rewrite response validation** (length ratio, content retention, refusal detection) with bounded retries, and exclusion of chunks that still fail. | `docs/DECISIONS.md` I5 | Engineering the book does not cover, but it changes which chunks reach the mean. Worth stating openly. |
| 5 | **`temperature = 0` cannot be sent to several current models**, which reject the parameter outright rather than ignoring it. Implemented as: send it where accepted, record its absence where not, and let the `M`-run standard deviations at M11 carry the determinism argument. | `docs/OPEN_QUESTIONS.md` Q14 | The specification pins a generation parameter that some candidate models will not accept. The mitigation is already the book's own (average over `M` runs, pin the version, log every call), but the deviation should be on the record before results are reported, not after. |

## Meeting record

Newest at the top. Keep entries short: what was raised, what was decided, what changed as a result.

**Entry template**

```
### YYYY-MM-DD — meeting N

**Present.**
**Raised.**
**Decided.** -> recorded as DECISIONS.md <id>
**Actions.** who / what / by when
```

---

### 2026-11-11 — meeting 1 of Phase B

**Present.** Dr. Renata Avros, Prof. Zeev Volkovich, Eliran Melihov, Miron Hanukaiev.
**Raised.** The start of Phase B. The implementation built in August was not shown.
**Decided.** Start the implementation now, and run the project in Google Colab. The team pays for the
API later. -> `docs/DECISIONS.md` I30 (Python 3.12 and 3.13 supported, because Colab runs 3.13).
**Actions.** Team: a Phase B specification and a Colab notebook that runs the pipeline, both shown at
the next meeting. Both done on 2026-11-21: the specification lives outside this repository, the
notebook is `notebooks/run_in_colab.ipynb`.

Phase A meeting notes live in the project folder outside this repository (`comments from meeting
7..11`).
