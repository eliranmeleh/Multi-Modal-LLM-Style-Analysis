# RUNBOOK

Operating a long, expensive job. `docs/ARCHITECTURE.md` explains how the system is built; this file
explains how to drive it and what to do when something goes wrong at call 4,000 of 7,500.

---

## Pre-flight, before any wide job

Run through this every time. It takes two minutes and it has prevented every expensive mistake that
would otherwise be worth listing here.

```bash
python -m mmlsa corpus verify                            # checksums, counts, set disjointness
python -m mmlsa run --config configs/full.yaml --dry-run # exact call count, token estimate, wall clock
python -m mmlsa cache stats                              # how much is already cached
```

- [ ] `corpus verify` passes.
- [ ] The dry-run call count is what you expected. If it is off by more than a few percent, find out why
      before starting. A wrong `P` or an unintended `include_ids` shows up here and nowhere else.
- [ ] `new calls`, under `TOTAL CALLS`, is what you mean to pay for. `already saved` counts the calls the
      cache already answers, at no cost. A repeat of a finished run should show `new calls 0`; a large
      number there means the wrong `llm.cache_dir`, another model, or a changed prompt (#21).
- [ ] `llm.model_id` is a **pinned dated snapshot**, not a floating alias. A floating alias makes the run
      unreproducible in principle.
- [ ] `run.seed` is the value you intend to publish.
- [ ] `llm.mode` is `live`, not `refresh`. `refresh` ignores the cache and re-pays for everything.
- [ ] The other person knows you are starting.

Then start it, detached, with the log captured:

```bash
python -m mmlsa run --config configs/full.yaml 2>&1 | tee runs/_live.log
```

## While it runs

The progress line reports completed, cached, failed and the current rate. Three things are worth
watching:

| Signal | Healthy | What it means if not |
|--------|---------|----------------------|
| Failed-chunk rate | under 1 percent | Validation is rejecting rewrites. Stop and inspect a few failures before burning the rest of the budget. |
| Cache hit rate | near 0 on a first run, near 100 on a re-run | A re-run with a low hit rate means something in the cache key changed unintentionally, usually a prompt template or a model id. |
| Throughput | steady | A sharp drop usually means rate limiting. Check the backoff counters in the log. |

Inspect progress without disturbing the job:

```bash
tail -f runs/_live.log
wc -l runs/<run_id>/calls.jsonl                        # calls completed so far
python -m mmlsa report --run-id <run_id> --partial     # partial scores from what has finished
```

## When it fails

**The job is resumable by construction.** Everything completed is in the cache, so restarting costs
nothing for work already done.

```bash
python -m mmlsa run --config configs/full.yaml --run-id <same_run_id>
```

Diagnosis by symptom:

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| `429` storms, throughput collapses | Provider rate limit | Lower `llm.concurrency` and `llm.requests_per_minute`, restart. The cache preserves everything done. |
| Many chunks failing validation | The model is adding preambles, refusing, or paraphrasing | Stop. Read ten failed responses in `calls.jsonl`. Fix the post-processing or the retry suffix, bump `prompt_schema_version`, restart. Do not loosen the thresholds to make the failures disappear. |
| `context length exceeded` on a profile call | A packing bin is too large | Lower `profile.context_budget_tokens`. Packing is deterministic, so the new packing is stable. |
| Model version changed mid-run | Provider rotated a floating alias | The run is flagged. Pin a dated snapshot and start a fresh run id. Do not publish a run that crossed a version change. |
| Out of memory | A whole creation is held in memory during profiling | Expected for the largest texts; profile calls stream from disk. If it persists, lower `llm.concurrency`. |
| Process killed by the OS or the machine slept | Nothing lost | Restart with the same run id. |
| `style profile describes one creation` | Nearly all the examples the profile quotes come from one creation (F-15, I37). Stopped after Step 1, so only the profile calls were spent | Read `profiles/run_<i>_merged.json` and `run_<i>_sources.json`. Do not re-run as it is: the cache returns the same profile. See `docs/OPEN_QUESTIONS.md` Q18 for the remedies. To finish the run anyway, for a pilot or a replay, resume it with `--set profile.source_check.on_one_source=warn`. |

## Interpreting the first results

Before reading any labels, look at the sorted scatter. In this order:

1. **Is there a visible gap?** If the 49 points form one continuous cloud, `tau` is a line through the
   middle of a single population and the labels mean nothing. Report that, do not tune around it.
2. **Where did the injected noise creations land?** They should be near the top. If a foreign text scores
   like an authentic one, the method is not measuring what it claims to measure. This is the cheapest
   sanity check available and it is free, because the noise texts are scored anyway.
3. **What is the spread across runs?** If per-creation standard deviation is comparable to the gap
   between the two groups, `M` is too low. Raise it, as the specification prescribes.
4. **Are the extremes sensible?** Read the highest-delta and the lowest-delta chunks. Both ends are where
   bugs surface first.

Only then look at which creations were flagged.

## Cost and cache management

```bash
python -m mmlsa cache stats            # entries, size on disk, hit rate by tag
python -m mmlsa cache prune --older-than 90d --tag rewrite
```

The cache is the project's most valuable artifact after the code. **Back it up before any large
experiment**, and never delete it to free disk space without archiving first: it is the difference
between re-running an analysis for free and paying for 7,500 calls again.

Note that changing `P` invalidates every rewrite cache entry, because the chunks themselves change.
This is the one place the cache cannot help, which is why the `P` sweep runs on the proof-of-concept
subset rather than the full corpus.

## Validation checks

The four checks of `docs/SPEC.md` section 7 (M14) run against a finished run of record, the
**baseline**, with the same `--config` and `--set` options as that run. Each prints its plan and
issues nothing without `--yes`; calls the baseline already made come from the cache.

```bash
python -m mmlsa experiment calibration --config C --baseline R --yes
python -m mmlsa experiment mixture     --config C --baseline R --yes
python -m mmlsa experiment heldout     --config C --baseline R --yes
python -m mmlsa run --config C --set noise.enabled=false            # the variant without noise, R2
python -m mmlsa experiment noise --config C --with-noise R --without-noise R2
```

**Recording a check for `pytest tests/validation`.** Make a bundle in
`tests/fixtures/recorded_runs/<check>/` (`noise` for noise robustness):

1. `runs/<run id>/`: a copy of the run directory or directories the check reads.
2. `cache/`: the saved answers the baseline and the check used. Copying the whole cache works;
   only the files of the baseline's and the check's `calls.jsonl` keys are needed.
3. `recording.yaml`: `config:` (the config file, relative to the repository), `set:` (the list of
   `--set` options, empty if none), and `baseline:`, or `with_noise:` and `without_noise:`.

`pytest tests/validation -q` then re-runs the check in replay mode, with no key and no call, prints
the measured value next to its condition, and fails if the check does not pass.

## Publishing a run

1. `python -m mmlsa report --run-id <run_id> --config <same> [--include <experiment run> ...]` writes
   `reports/<run_id>/`: `report.md`, its tables as CSV and the run's figures. It sends no request and
   never writes into the run directory. Commit `reports/<run_id>/`.
2. Commit the small artifacts: `manifest.json`, `config.snapshot.yaml`, `scores.csv`,
   `threshold.json`, `noise_diagnostics.csv`, `figures/` (`git add -f`, since `runs/` is ignored).
3. `python -m mmlsa release --run-id <run_id> [--run-id <another> ...] --config <same>` writes
   `release/<run_id>.tar.gz` and its `.sha256`: each run directory whole, plus exactly the cache
   entries its `calls.jsonl` used, so the archive replays without the rest of `cache/`. It stops if
   an entry is missing. Attach both files to a GitHub release; `release/` is never committed.
4. Add the finding to `docs/RESULTS.md`, with the run id and the release URL.
5. Verify the run replays from the archive alone: unpack it into an empty folder and run
   `python -m mmlsa reproduce --run-id <run_id> --set run.out_dir=<folder>/runs --set
   llm.cache_dir=<folder>/cache`. It must print `REPRODUCED`.

Step 5 is not optional. A run that cannot be replayed cannot be defended. Replay needs no key once
#37 is merged; before that, a run made with a live provider also needs that provider's SDK and a
placeholder key in the environment, though nothing is sent.
