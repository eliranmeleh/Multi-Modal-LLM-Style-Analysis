# Review: the Colab notebook and the cost estimate

**Date:** 2026-11-23. **Reviewer:** Miron. **Reviewed at:** `8e23d85` (`main`).
**Scope:** `notebooks/run_in_colab.ipynb` as committed on 2026-11-21, and the cost estimate in
`docs/STATUS.md`. Nothing in `src/` is changed by this review; every item below is a proposal for
discussion, and where a fix belongs in code it is described rather than made.

---

## What was checked

| Part of the notebook | Checked | How |
|---|---|---|
| 1. Setup | partly | Read; the non-Colab branch was exercised by running Parts 2 and 3 locally |
| 2. The corpus | yes | `python -m mmlsa corpus verify`: 70 checks passed |
| 3. The whole method on a tiny example | yes | `run --config configs/mini.yaml` with the notebook's `--set` overrides: 19 fake calls, `tau = 0.0517` (otsu_exact), 1 of 3 suspicious (`mini_beta`), run id `20261123T1002-f763e87e-s20260731-mini` |
| 4. The method on real text | no | Needs a key |
| 5. Run it again | no | Needs a key |

Parts 4 and 5 were reviewed by reading only, against the CLI (`compare --help`) and the configs.

## What works well

- Every cell drives the CLI rather than reimplementing it, so what runs in Colab is what the test
  suite covers.
- Results and the response cache live on Drive, so a disconnect never loses a paid answer.
- The side-by-side passage view with the changed function words highlighted, followed by the FWED
  arithmetic that reproduces the recorded delta, is the clearest explanation of Step 4 we have. It
  is worth showing the supervisors as it is.
- The free-tier handling (`tokens_per_minute`, `max_transient_retries`) is grounded in a measured
  failure (`RESULTS.md` F-12) rather than guessed.

## Findings

Ordered by how much they matter for M10 onward.

### N1. `FREE_TIER = False` does not speed anything up

**Where:** `cell-02`, `cell-17`.
Turning the flag off only drops the two free-tier overrides. The request rate then falls back to
`configs/default.yaml`: `llm.requests_per_minute: 4` and `llm.concurrency: 1`. With a paid key, the
full-corpus run (9,018 calls including retries, see C1 below) would take about 37 hours at 4 calls a
minute.

**Proposal:** a `PAID` branch that sets `llm.requests_per_minute`, `llm.concurrency` and
`llm.tokens_per_minute` to the paid tier's limits (STATUS suggests 240 and 8), applied to every
`run` and `compare` the notebook issues.

### N2. Part 4 runs `compare`, not the pipeline

**Where:** `cell-17`.
`compare` is the M9 model-comparison harness: one profile, `CHUNKS` sampled passages, one run, no
noise, no threshold. It is the right tool for showing Steps 1 to 4, but no cell runs the pipeline
itself, so the notebook cannot carry M10.

**Proposal:** a Part 6 for the proof of concept, in this order:
1. `run --config configs/poc.yaml --dry-run`, and print the call count and an estimated cost;
2. a confirmation variable that must be set to run;
3. `run --config configs/poc.yaml` with the paid settings from N1;
4. `scores.csv`, `threshold.json` and the sorted scatter, as in Part 3;
5. a short note on continuing with `--run-id` after Colab disconnects.

### N3. No token or cost read-out

**Where:** `cell-08` (the `mmlsa` helper).
The helper prints how many answers were new and how many came from the cache, but not what they
cost. The ledger already records `input_tokens` and `output_tokens` for every call
(`src/mmlsa/llm/ledger.py`), so the totals are available.

**Proposal:** after each live part, print the input and output tokens and an estimated dollar cost
from a small price table set in `cell-02`. Once the key is paid, this is the number we will want to
see every time.

### N4. `MODEL` applies to `compare` only

**Where:** `cell-02`, `cell-17`.
`MODEL = "gemini-3.1-flash-lite"` reaches `compare` through `--model`. A `run` issued from the
notebook would use `llm.model_id: null`, which resolves to the provider default,
`gemini-3.5-flash`. On 2026-11-23 Google's pricing page lists `gemini-3.1-flash-lite`,
`gemini-3.5-flash-lite`, `gemini-3.6-flash` and `gemini-3.8-flash`, but not `gemini-3.5-flash`,
so the default may no longer be served at all.

**Proposal:** pass `--set llm.model_id=<MODEL>` on every `run`, and settle the model of record at
the next meeting (agenda item B), then pin it in `configs/default.yaml`.

### N5. One cache file per call, written directly to Drive (untested risk)

**Where:** `cell-13`, `cell-17` (`llm.cache_dir` under `SAVE_DIR` on the Drive mount).
`ResponseCache` writes one JSON file per call with an atomic rename. M12 alone is about 9,000
files and the whole of Phase B about 28,000. The Drive mount is slow with many small files and its
rename semantics are not those of a local disk. This has not been measured; it may be fine.

**Proposal:** measure it on a run of about 200 calls before M10. If it is slow or flaky, keep the
cache under `/content` during a part and copy it to Drive at the end of the part.

### N6. Part 5 promises more than it does

**Where:** `cell-26`, `cell-27`.
The text says the peer examiner will reproduce the results without a key. Without a key,
`LIVE_OK` is false and Part 5 is skipped; and even with one, the cache it replays from is the
runner's own Drive folder, which the examiner does not have.

**Proposal:** either narrow the wording to "re-running on the same account costs nothing", or add
the path agenda item D asks for: a published cache or run artifacts, replayed with
`--mode replay`.

### N7. Small items

- `cell-04`: if the repository folder already exists in the runtime, it is not updated, so a second
  "Run all" in the same session uses the old code. A `git pull --ff-only` (or pinning a ref and
  printing the commit) closes that. Run directories already record `git_commit` in `manifest.json`,
  so traceability of `run` output is not affected.
- `cell-21`: a `PASSAGE` larger than the number of rewrites that passed validation raises an
  `IndexError`; a bounds check with a one-line message would be friendlier.

## The cost estimate

`docs/STATUS.md` estimates the remaining project at under 20 dollars. A recount suggests about
twice that.

### C1. Calls and tokens

Call counts are from `run --dry-run` on `poc`, `full`, `sensitivity` and `control`, with the
remaining experiments scaled from them. Assumptions: about 1,500 tokens of profile in every rewrite
prompt, 10 per cent of calls retried, output the length of the passage, and no cache reuse between
milestones, so this is an upper bound.

| Milestone | Calls | Input tokens | Output tokens |
|---|---|---|---|
| M10 proof of concept | 1,071 | 3.0M | 0.7M |
| M11 stability and `P` sweep | 6,829 | 15.5M | 3.9M |
| M12 full corpus | 9,018 | 25.1M | 5.9M |
| M13 control (Mode B over the corpus) | 2,929 | 2.1M | 1.9M |
| M14 held-out, no-noise variant, mixture | 8,176 | 21.0M | 5.2M |
| **Total** | **about 28,000** | **67M** | **18M** |

### C2. The token estimator runs low

The profile request for *Macbeth* and *Henry VIII* in F-12 was 69,883 input tokens for 44,120
words, which is **1.58 tokens per word**. `profile.tokens_per_word` is 1.35, so every dry-run
estimate is about 17 per cent under. Early Modern spelling tokenizes into more pieces than modern
English. Worth either raising the default or calibrating it from the provider's token-counting
endpoint where one exists.

### C3. Cost by model

Prices per million tokens from Google's pricing page and the providers' published rates on
2026-11-23. The last column adds 50 per cent for reruns and failures.

| Model | Input / output | Total | With margin |
|---|---|---|---|
| `gemini-3.1-flash-lite` | $0.25 / $1.50 | about $43 | about $65 |
| `gemini-3.1-flash-lite`, Batch API | $0.125 / $0.75 | about $22 | about $32 |
| `gemini-3.5-flash-lite` | $0.30 / $2.50 | about $64 | about $96 |
| `gemini-3.8-flash` (doubles on 2027-01-01) | $0.75 / $3.75 | about $116 | about $174 |

The Batch API halves the cost, but the runner issues synchronous requests and would need a new
path through the cache and the ledger; at this size it is probably not worth it.

## Suggested order

1. N4 and N1 before any paid call, because they decide which model runs and how fast.
2. N5, measured once, before M10.
3. N2 and N3 together, as the notebook's M10 part.
4. N6 and N7 whenever convenient.
5. Update the estimate in `docs/STATUS.md` once the model of record is settled.

## Response, 2026-11-24

| Finding | State |
|---|---|
| N1 | **Done.** `TIER = "free" \| "paid"` and a `LIMITS` table in Part 1, applied to every live command |
| N2 | **Done.** Part 6 runs `configs/poc.yaml` in the order proposed; Part 4 says it runs `compare` |
| N3 | **Done.** `cost_report` after every live part, priced from `PRICES` in Part 1 |
| N4 | **Done** for the notebook: every `run` passes `llm.model_id=MODEL`. Pinning it in `configs/default.yaml` waits for agenda item B |
| N5 | **Tooling done, not yet measured.** Part 7 times the writes on Drive; `CACHE_ON_DRIVE = False` is the fallback. Needs one run in Colab |
| N6 | **Done.** Part 5 promises a free rerun on the same account and points to agenda item D |
| N7 | **Done.** `git pull --ff-only` on an existing clone, the commit printed; `PASSAGE` clamped with a message |
| C1 to C3 | The cost line in `docs/STATUS.md` now quotes this recount. C2 (the token estimator) is unchanged in code; Part 6 corrects for it in its estimate only |

