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

## Publishing a run

1. `python -m mmlsa report --run-id <run_id>` generates the tables and figures.
2. Commit the small artifacts: `manifest.json`, `config.snapshot.yaml`, `scores.csv`,
   `threshold.json`, `noise_diagnostics.csv`, `figures/`.
3. Gzip `rewrites/`, `deltas/` and `calls.jsonl`, attach them to a GitHub release, and record the
   release URL in `manifest.json`.
4. Add the finding to `docs/RESULTS.md`, with the run id.
5. Verify the run replays: `python -m mmlsa run --config <same> --mode replay` reproduces `scores.csv`
   byte for byte.

Step 5 is not optional. A run that cannot be replayed cannot be defended.
