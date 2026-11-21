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

**Show first:** the pipeline running in Google Colab, `notebooks/run_in_colab.ipynb`. The supervisors
have not seen the implementation yet; meeting 1 asked for it to start.

| # | Item | Source | Why it needs them |
|---|---|---|---|
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
