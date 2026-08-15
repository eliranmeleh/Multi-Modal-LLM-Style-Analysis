# GLOSSARY

Symbols, terms and naming conventions. Kept short on purpose. Use these names in code, in commit
messages, in the report and in conversation, so that one thing has one name everywhere.

---

## Symbols

| Symbol | Code name | Meaning |
|--------|-----------|---------|
| `P` | `chunking.P` | Chunk length in words. Pilot default 400, range 200 to 600. |
| `M` | `run.M` | Number of independent runs whose scores are averaged. Pilot default 3. |
| `T_max` | `purification.T_max` | Maximum purification iterations. Phase B only, optional. |
| `delta`, δ | `delta` | Style distance between one chunk and its rewrite. In `[0, 1]`. |
| `tau`, τ | `tau` | The classification threshold. Above it, suspicious. |
| `alpha`, α | `experiment.control.alpha` | Significance level for the control experiment. 0.05. |
| `s_i(w)` | `score_run_i` | Score of creation `w` in run `i`: the mean chunk delta. |
| `score(w)` | `score_mean` | Final score of creation `w`: the mean of the `M` per-run scores. |
| `FW(x)` | `function_words(x)` | The ordered sequence of function words in text `x`. |
| `lev` | `sequence_levenshtein` | Levenshtein distance between two token sequences, not characters. |
| `N` | `n_creations` | Number of creations in the target corpus. 49 in the running case. |
| `k` | `n_profile_bins` | Number of profile-extraction calls after packing. |

## Terms

**Creation.** One text in the corpus. The project uses "creation" rather than "work" throughout the
book, the deck and the code, and that vocabulary is deliberate. `creation_id` is the stable snake_case
identifier, for example `henry_viii`.

**Chunk.** A consecutive run of `P` words from one creation. The unit of rewriting and of measurement.
Identified by `(creation_id, chunk_index)`.

**Profile.** The description of the corpus's dominant style produced by the LLM in Step 1. One per run,
shared by every chunk scored in that run.

**Run.** One complete pass through Steps 1 to 5 with its own independently extracted profile. There are
`M` of them. Not to be confused with a **job**, which is one invocation of `mmlsa run` and contains all
`M` runs.

**Style distance.** The generic name for the Step 4 measurement. **FWED** is one implementation of it.
Use "style distance" when speaking about the method and "FWED" when speaking about the specific metric.
The specification is deliberate about this: FWED is the metric the method is developed with, one of a
family compared in Phase B, and never "the chosen metric".

**Noise injection.** Adding one foreign creation to the corpus before profile extraction, in runs 2
through `M`. Run 1 is plain. Never cumulative.

**Foreign creation / intruder.** A text from outside the target corpus. Used for noise injection, for
the held-out test and for the mixture test, always from disjoint sets.

**Control experiment.** Mode A (rewrite under the extracted profile) versus Mode B (rewrite under a
generic "in `<author>`'s style" prompt), on the same chunks, paired.

**Purification.** Re-extracting the profile from the authentic-only set and repeating. **Not** part of
the Phase A method. Optional in Phase B, adopted only if the single-round threshold proves unstable.

**Borderline.** A creation whose score sits within `classify.borderline_band` of `tau`, or whose spread
across runs crosses `tau`. Reported as a third category even though the classifier stays binary.

**Consensus cases.** The five creations where scholarly consensus on co-authorship is firmest:
Henry VIII, Henry VI Parts I, II and III, Timon of Athens. Success metric 3 requires four of five.

## Infrastructure terms

**Cache key.** The `sha256` that identifies an LLM call by its full content. See
`docs/ARCHITECTURE.md` section 4.

**Ledger.** `runs/<run_id>/calls.jsonl`. Every call, including cache hits. Implements the auditability
requirement.

**Replay mode.** Running entirely from the cache, where a miss is a hard error. Reproduces a recorded
run exactly, offline, with no API key.

**Run id.** `<UTC date>T<HHMM>-<config_hash[:8]>-s<seed>`. Immutable once written.

**Job.** One invocation of `mmlsa run`. Contains `M` runs.

## Naming conventions in code

- `creation_id`, `chunk_index`, `run_index` are the three identifiers. Always in that order.
- Anything derived from an LLM call carries the `cache_key` that produced it.
- Per-run quantities are suffixed `_run_i`; averaged quantities are suffixed `_mean` or `_std`.
- Never abbreviate `creation` to `work` or `doc` in code. One thing, one name.
