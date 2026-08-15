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

| # | Item | Source | Why it needs them |
|---|---|---|---|
| 1 | The profile **merge call**. The corpus does not fit one context window, so extraction is split across `k` calls; the book specifies the split but leaves consolidation implicit. We add one merge call. | `docs/OPEN_QUESTIONS.md` Q1, `docs/DECISIONS.md` I3 | It is an addition to the specified method, however small. Better confirmed than assumed. |
| 2 | Scoring the **injected noise creation** as a diagnostic, excluded from `tau` and from the reported set. | `docs/OPEN_QUESTIONS.md` Q2, `docs/DECISIONS.md` I7 | Free evidence that the pipeline works; confirm it does not count as changing the method. |
| 3 | **Model choice** for the pipeline LLM. The book defers this to the proof of concept. Plan: compare candidates at M9 on ten identical chunks and decide on measured rewrite fidelity and stability. | `docs/PLAN.md` M9, `docs/DECISIONS.md` S9 | They may have a preference, or access to a model we do not. |
| 4 | **Rewrite response validation** (length ratio, content retention, refusal detection) with bounded retries, and exclusion of chunks that still fail. | `docs/DECISIONS.md` I5 | Engineering the book does not cover, but it changes which chunks reach the mean. Worth stating openly. |

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

*No Phase B meetings recorded yet. Phase A meeting notes live in the project folder outside this
repository (`comments from meeting 7..11`).*
