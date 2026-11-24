# SESSION LOG

Append-only. One entry per working session, newest at the top. Never edit or delete a past entry;
if something recorded here turns out to be wrong, say so in a later entry.

This is the project's memory. `docs/STATUS.md` says where we are *now*; this file says how we got
here and, crucially, **why** — the reasoning that would otherwise be lost between sessions.

**Entry template**

```
## YYYY-MM-DD — <one-line goal>

**Goal.** What this session set out to do.
**Done.** What actually changed, with file paths.
**Verified.** The command that proves it, and its result. Not "it should work".
**Decided.** Any judgement call taken, and why. Cross-reference docs/DECISIONS.md if it is durable.
**Surprised by.** Anything that did not behave as expected. This is the highest-value line.
**Next.** The single next action, concretely enough to start cold.
```

---

## 2026-11-24 (evening) — The Colab cache verified across sessions; Miron's pull requests reviewed.

**Goal.** Check that a re-run in Colab costs nothing, review Miron's follow-ups to the reviews of
#10, #11 and #13, and leave the board current.

**Done.** Ran the notebook in Colab twice with Drive mounted, deleting the runtime in between
(`docs/RESULTS.md` F-14). Checked #11's follow-up commit on `main` and #13's on its branch, approved
#13, answered #14, and opened #15 on the em dash. `docs/STATUS.md`: quality gates, CI, the
current milestone, next actions.

**Verified.**
- In Colab, the second session's Part 4: `Model answers: 0 new, 7 from saved copies`, `$0.00`,
  deltas equal to the first session's.
- On `main` at `b8916f3`: `MMLSA_ALLOW_LIVE=0 pytest -q` 623 passed; `ruff check`,
  `ruff format --check` and `mypy src` clean. CI green at `b8916f3`.
- On #13 at `330ed89`: Part 1, then cells 29, 31, 33 and 35 alone, ran without an error, and the
  dry run printed about $1.48. `copy_new_files` copied 0 files on a second save, also with
  modification times rounded down to whole seconds as Drive may keep them, and 1 for one new file.

**Decided.** On #14: refuse a resume under a different commit unless `--allow-code-change` is given,
and record the commit and whether the working tree had uncommitted changes when the run starts.
Miron's proposal, with the second half added; open until he answers.

**Surprised by.**
- The morning's Colab run kept its answers on the runtime disk (F-13), so they were paid for again
  tonight: 3 cents here, but the same slip on M12 would cost about 12 dollars.
- `--dry-run` reports every call as new; it never looks in the cache.
- The profile names both plays, although the prompt gives no titles (F-14).
- An em dash with no spaces joins two words into one token (F-14, #15).

**Next.** Push `eliran/4-run-index-cache-key` from the second computer and open its pull request;
it must be merged before M11.

---

## 2026-11-24 — Each of the `M` runs gets its own answers from the model.

**Goal.** Put the run index into the cache key before M11, so that runs on identical inputs are
independent samples rather than run 1's cached answers served again (`docs/STATUS.md` next action 5,
issue #4). Approve Miron's working agreement, issue #5.

**Done.**
- `src/mmlsa/llm/base.py`: `LLMRequest.replicate`, counted from 1. `cache_fields` adds it only from 2
  upward, so replicate 1 hashes exactly as before.
- `src/mmlsa/pipeline/rewrite.py` and `profile.py`: the rewrite, extraction and merge request builders
  take `replicate`; `rewrite_chunks` and `extract_profile` pass their `run_index`. `compare` is
  untouched and stays at replicate 1.
- `tests/unit/test_replicate.py` (11 tests) and one integration test in
  `tests/integration/test_orchestrator.py`.
- `docs/DECISIONS.md` I32, `docs/ARCHITECTURE.md` section 4, `docs/TRACEABILITY.md` N1,
  `docs/STATUS.md`.
- Issue #5 approved and closed on GitHub.

**Verified.**
- Run 1's keys match three golden values computed on `15513b3` before the change.
- With the replicate removed from the key again, 7 of the new tests fail, among them the mini run with
  noise off, where run 2 was served entirely from run 1's entries. With it, all pass, and a second run
  of the same configuration still makes no provider call.
- Quality gate, after rebasing onto `b8916f3` (PR #11 merged): **635 tests pass** on Python 3.11 (623 before, plus 12); `ruff check`,
  `ruff format --check` and `mypy src` clean.

**Decided.** I32: the profile calls carry the index too, because Stage 2a asks for independent runs of
the whole method; leaving replicate 1 out of the hash keeps every paid answer valid. Nothing in
`docs/SPEC.md` conflicts, so no open question.

**Surprised by.** A second content-validation retry is not a new attempt. Retry rounds 1 and 2 send the
same retry prompt at the same replicate, so round 2 is served round 1's failed answer from the cache,
and `rewrite.max_retries: 2` gives one real retry. Not changed here; it needs its own fix.

**Next.** The Gemini provider default (#4, Miron's under #5), then M10's dry run.

---

## 2026-11-24 — Billing is set up on the API project.

**Goal.** Move the project's Gemini key off the free tier, which cannot carry M11 to M14 (F-13).

**Done.** Set up billing on `mmlsa-phase-b` in Google AI Studio: a Cloud billing account on
prepay, the minimum prepayment, auto-reload off, and the Google Cloud credit available to the team
applied to the account. `docs/STATUS.md` key, quota, blocked and next-action lines.

**Verified.** AI Studio shows the key on **Tier 1** and the credit as eligible on the billing
account; the prepayment's invoice is in Cloud Billing, Transactions, *Prepay - AI Studio*.

**Decided.** Prepay rather than postpay, with auto-reload off: when the balance runs out the key
returns HTTP 402 instead of charging further, so no run can overspend by mistake.

**Surprised by.**
- The Google Cloud free trial's 300 dollars does not cover the Gemini API (since March 2026), and a
  free-trial billing account is not eligible for the paid tier. The right path is AI Studio's
  *Set up billing*, not the Cloud console's trial sign-up.
- Promotional credit is spent before the prepaid balance, but a prepaid balance must exist before
  any credit can be drawn.

**Next.** At the meeting, settle Q10 and agenda items B and C; then M10 with `TIER = "paid"`.

---

## 2026-11-24 — The notebook runs live in Colab, and the remaining project is costed from measurement.

**Goal.** Run the notebook in real Google Colab before the next meeting, and work out from our own
counts what the rest of the project costs on Gemini, how many calls it needs, and whether the
project's API access is enough.

**Done.**
- Ran every part of `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb` in Colab against the project
  `mmlsa-phase-b`, in a session without Drive mounted.
- Counted the calls of every remaining experiment with `run --dry-run` and each experiment's
  settings, and priced them with a token model fitted to F-11 and F-12.
- Read the project's quotas and tier in Google AI Studio and the current prices on Google's pricing
  page.
- `docs/RESULTS.md` F-13; `docs/STATUS.md` model, key, quota, blocked and next-action lines.
  `docs/OPEN_QUESTIONS.md` Q17.

**Verified.** In Colab: 70 corpus checks pass; Part 4 made 7 live calls on `gemini-3.1-flash-lite`,
76,853 input and 4,268 output tokens; the explained passage scored FWED 0.0899 as on 2026-11-21;
Part 5 replayed with no calls and identical deltas. The token model predicted the live call within
0.5 per cent.

**Decided.** Nothing durable; the model of record and the budget are agenda items B and C. The
costing counts upper bounds and leaves the optional M17 out.

**Surprised by.**
- The free tier for the two flash-lite models is now 500 requests a day, not 20, which makes M10
  feasible without billing.
- `gemini-3.5-flash`, our provider default, has disappeared from both the price list and the
  project's model list.
- The full corpus's profile requests, about 560,000 tokens each, can never pass the free tier's
  250,000 tokens a minute, so the free tier stops at M10 no matter how long one waits.
- M12 plans 8,270 calls, not the 7,500 the documents quote.
- The extracted profile is 316 words, a third of what the earlier estimate assumed.
- Colab returned 503 (busy) eleven times before seven calls succeeded; the retries absorbed it.

**Next.** At the meeting, settle agenda items B and C with the measured 37 to 47 dollars; then either
set up billing or start M10 on the free tier with `llm.model_id=gemini-3.1-flash-lite`.

---

## 2026-11-24 — The notebook acts on Miron's review, and can carry M10.

**Goal.** Apply the notebook findings N1 to N7 of `docs/reviews/2026-11-23-colab-notebook-and-cost.md`
so the notebook is ready for the next meeting and for M10 once a paid key arrives. Set the project
up on a second computer.

**Done.**
- `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb`, Part 1: `TIER = "free" | "paid"` with a `LIMITS`
  table applied to every live command (N1); `PRICES` per model (N3); `RUN_POC`, `POC_RUN_ID` and
  `CACHE_ON_DRIVE`. Setup now runs `git pull --ff-only` on an existing clone and prints the commit (N7).
- The `mmlsa` helper returns what the tool printed; new `limit_settings`, `dollars` and `cost_report`,
  which totals the tokens of the new answers in a run's `calls.jsonl` and prices them (N3).
- Part 6, the proof of concept (N2): `run --config configs/poc.yaml --dry-run` with a token and cost
  estimate using the review's assumptions (C1, C2), a run gated on `RUN_POC` and `TIER = "paid"`, the
  scores, threshold and scatter, the check of the prediction written in `configs/poc.yaml`, and
  `--run-id` to continue a run that Colab cut off. Every `run` passes `llm.model_id=MODEL` (N4).
- Part 7, optional and free: times 200 cache-style writes (temporary file, then rename) on Drive and on
  the Colab disk (N5). With `CACHE_ON_DRIVE = False` the cache lives on the Colab disk and new answers
  are copied to Drive at the end of each live part.
- Part 4 states that it runs `compare`, not the pipeline (N2); Part 5 promises only a free rerun on
  the same account, and names agenda item D for the examiner's path (N6); `PASSAGE` out of range now
  shows the last usable passage with a one-line message (N7).
- `docs/STATUS.md`: CI line, the cost estimate, the notebook row, the second computer.

**Verified.**
- The notebook executed end to end outside Colab with no key: Parts 1 to 3 ran (tau 0.0517,
  `mini_beta` suspicious, as on 2026-11-21), Parts 4 to 6 were skipped with their messages, and the
  Part 6 dry run printed 972 calls and an estimate of 2.9M input and 0.7M output tokens, about
  $1.74 on `gemini-3.1-flash-lite`; the review's C1 counted 3.0M and 0.7M for M10.
- Executed again with the live parts pointed at `FakeProvider`, `TIER = "paid"` and `RUN_POC = True`:
  Part 4 (6/6 usable, the notebook's FWED equal to the recorded delta), Part 5 (0 new answers, same
  numbers), Part 6 (972 planned calls, run complete, scores, threshold, prediction check) and the
  Part 7 timing function all ran. The numbers mean nothing with the stand-in model.
- 617 tests pass on Python 3.11; `ruff check`, `ruff format --check` (which covers the notebook) and
  `mypy src` clean. CI green at `4df8129` on 3.11 and 3.13.

**Decided.** The paid limits in the notebook are 240 requests a minute at concurrency 8, the values
`docs/STATUS.md` already suggested; they still need checking against the project's real paid quota.
Part 6 refuses to run on the free tier rather than pacing ~970 calls across seven weeks.

**Surprised by.** Running Part 3 twice within one minute fails: the run id is stamped to the minute,
so the second run gets the id of the first, complete one, and R9 refuses it. Correct behaviour, but a
second "Run all" in quick succession stops the notebook. Not changed; worth a sentence in the
notebook or a finer timestamp if it bites. Also, the run id's config hash includes the rate limits,
so the same experiment on the free and the paid tier gets different run ids.

**Next.** Show the notebook at the next meeting and record the answers to agenda items A to I in
`docs/DECISIONS.md`. When the paid key arrives, run Part 7 once, then Part 6.

---

## 2026-11-21 — The pipeline runs in Google Colab, as meeting 1 asked.

**Goal.** Act on meeting 1: the supervisors asked for implementation to start and for the project to
run in Google Colab. Make the existing pipeline installable there, and build a notebook to show at the
next meeting.

**Done.**
- `pyproject.toml`: `requires-python = ">=3.11"`, and numpy no longer capped below 2.0
  (`docs/DECISIONS.md` I30, which widens S12).
- `.github/workflows/ci.yml`: the check job runs on Python 3.11 and 3.13.
- `notebooks/run_in_colab.ipynb`: clones and installs the repository in Colab, keeps results and the
  response cache on Google Drive, runs the whole method offline on `configs/mini.yaml`, then a live
  `compare` on *Macbeth* and *Henry VIII* showing the profile, a passage beside its rewrite with the
  changed function words highlighted, and the FWED arithmetic, then the same command again from the
  cache. It drives the CLI rather than re-implementing anything, so what runs in Colab is what the
  tests cover.
- `README.md` (Colab section and badge), `CLAUDE.md` section 4, `docs/MEETINGS.md` (meeting 1 and the
  next agenda), `docs/STATUS.md`, `docs/RESULTS.md` F-12.
- Outside the repository: a Phase B specification, in English and in Hebrew.

**Verified.**
- **617 tests pass on Python 3.13** (numpy 2.5.5, pandas 3.1.1) and **on a fresh 3.11 install**
  (numpy 2.4.6, pandas 3.1.1), which is what CI resolves now that numpy is uncapped. `ruff check`,
  `ruff format --check` and `mypy src` clean.
- The notebook executed end to end on 3.13 with a live key in 2 minutes: 70 corpus checks; the mini
  run's tau 0.0517 with `mini_beta` suspicious, the same as on 3.11; 6 of 6 live rewrites usable; the
  notebook's own FWED, 17 edits over 189 function words = 0.0899, equals the pipeline's recorded
  0.089947; the rerun issued no calls and reproduced every delta.

**Decided.** I30. The notebook paces the free tier itself (`FREE_TIER`) instead of changing
`configs/default.yaml`, because the runs of record are planned on a paid key.

**Surprised by.** Colab's newest runtime is already Python 3.13, not 3.12, and numpy 1.26 has no 3.13
build, so the numpy cap alone would have broken installation. And the free tier caps input tokens at
250,000 a minute: three 503s on a 70,000-token profile request, each retried in full, used the whole
minute's quota (F-12).

**Next.** Show the notebook at the next meeting and record the answers to agenda items A to I in
`docs/DECISIONS.md`.

---

## 2026-08-29 (tenth) — The first real calls, and what only they could tell us.

**Goal.** A key arrived. Close M9: make real calls and produce the measured comparison the milestone
has been waiting on since 2026-08-16.

**Done.**
- Installed the `gemini` extra (`google-genai 2.20.0`) and created `.env`. `uv` needs
  `--link-mode=copy` inside OneDrive; the default hardlink fails with `os error 396`.
- `src/mmlsa/llm/providers/gemini.py`: model table replaced with the current families, every
  `reasoning` value **measured against the service** rather than read off documentation. Default model
  is now `gemini-3.5-flash`.
- `src/mmlsa/pipeline/rewrite.py`: `is_refusal`, anchoring the refusal-marker scan to the opening of a
  response. New `rewrite.validation.refusal_scan_chars`, wired through `config.py`, `compare.py`,
  `orchestrator.py` and `configs/default.yaml`.
- `src/mmlsa/llm/runner.py`, `llm/base.py`, `providers/{fake,replay,_live}.py`: providers carry
  `sends_requests`, and the runner does not rate limit a backend that issues none.
- `configs/default.yaml`: 4 requests per minute at concurrency 1, sized to the measured free tier.
- Four new tests in `tests/unit/test_rewrite_validation.py`. `docs/DECISIONS.md` I27, I28, I29;
  `docs/OPEN_QUESTIONS.md` Q14 partly answered, Q15 and Q16 raised; `docs/RESULTS.md` F-09, F-10, F-11.

**Verified.**
- **617 tests pass in 43 seconds.** `ruff check`, `ruff format --check`, `mypy src` clean. All seven
  configs resolve.
- **M9's acceptance artifact exists:** `runs/compare-20260829T1247-s20260731/summary.md`, two models on
  ten identical chunks. `gemini-3.5-flash` 7/10 usable, delta 0.0516, latency 2814 ms;
  `gemini-3.1-flash-lite` 10/10, delta 0.0323, 3098 ms. Neither needed cleaning on any chunk.
- Re-running the comparison issues nothing new: profile and eight rewrites came back `cached` (R3).
- The refusal fix checked against the two real responses it wrongly rejected: both now accepted, at
  content retention 0.988 and 0.962.

**Decided.**
- **`gemini-3.5-flash` as the model of record, `gemini-3.1-flash-lite` recommended for the runs**
  (I28, F-11). Not on the delta — a lower delta is not a better model — but because it completed every
  chunk, altered layout least, and did not insert words. `gemini-3.5-flash` inserted "yfaith" into a
  passage, which is content the original did not have being measured as style.
- **The refusal scan is anchored to the opening** (I27) rather than the whole response, with the
  window in config and 0 restoring the old behaviour.
- **Rate limiting follows the provider, not the config file** (I29). Fixing it in `configs/mini.yaml`
  would have been a trap in the other direction, since `compare -m gemini:...` selects a live model
  while still reading that file.

**Surprised by.** Four things, and the first two change the plan.

1. **The configured model could not be called at all.** `gemini-2.5-flash` returns 404 to any project
   created after its cutoff — "no longer available to new users". It is still listed by
   `models.list()`, so the catalogue is not the authority on what a key can reach. Every model
   capability in the table is now measured, because the documentation was not load-bearing.

2. **The free tier is 20 requests per day per model**, not just 5 per minute. The per-minute wall was
   loud and immediate; the daily wall arrived quietly, after the day's twentieth call, and it is the
   one that matters. M10 needs ~750 rewrite calls and M12 ~7,500, so the free tier gives about five
   weeks for the former and a year for the latter. **This is now the project's blocking decision**, and
   the answer is probably billing: the whole remaining project is under 20 dollars at flash pricing.

3. **The refusal check was discarding lines of dialogue.** Two chunks came back full-length, in style,
   with content retention above 0.96, and were rejected as refusals — because a character says "I will
   not kiss thee" and, elsewhere, "Keep it, I cannot eat it". The markers were matched as substrings
   anywhere in the response, and they occur in the *original* too, so the check was not reading the
   model at all. The damage is the manner of the loss: chunks were dropped **as a function of their
   content**, so what survived was a biased sample of the creation. 612 offline tests never caught it
   and could not have — we wrote the pathological responses ourselves, and we wrote refusals that look
   like refusals. It took one real play's dialogue.

4. **The mini fixture actively misled.** On it, the model produced a *contrastive* profile — "Creation
   1 employs archaic diction, while Creation 2 modernizes" — and then wrote three versions of every
   passage under headings, blowing every length check with ratios up to 11.6. It looked like a broken
   prompt. On real text, same code, same prompts: single profile, clean rewrites, length ratio within
   1 per cent, zero responses needing cleaning. Three deliberately dissimilar short fixtures are not a
   rehearsal for a single-author corpus. Kept as Q15 anyway, because a `k`-bin of the real corpus could
   in principle provoke the same shape and it would not fail loudly.

**Next.** The billing decision (see `docs/STATUS.md` Next actions). Nothing downstream can start until
it is settled. Then Q10, then M10 with `--dry-run` first.

---

## 2026-08-16 (ninth) — M9's harness: the comparison as an artifact, not an afternoon.

**Goal.** M9's deliverable needs a key. Its *tooling* does not. Build the thing that produces the
acceptance artifact so the milestone is one command when a key arrives.

**Done.**
- `src/mmlsa/pipeline/compare.py` and `mmlsa compare`. Every candidate rewrites the **same**
  deterministically selected chunks; the command writes `summary.md` (the written comparison),
  `comparison.csv`, `summary.json`, `profiles/`, `calls.jsonl`, and `rewrites/` — one file per
  passage with every model's version beneath it.
- `tests/integration/test_compare.py`, 19 tests over the mini corpus with the offline provider.
- `docs/ARCHITECTURE.md` section 8, `docs/TESTING.md` section 7, `docs/PLAN.md` M9, `docs/STATUS.md`.

**Verified.**
- 612 tests pass (was 593). `ruff`, `ruff format`, `mypy` clean. 97 per cent on `compare.py`.
- Run end to end against `configs/mini.yaml` with three candidates, two offline and one live: plan
  printed, `--yes` issued 15 calls, artifacts written, the live candidate recorded as unavailable
  with the install command in its message while the other two were measured.
- Re-running the same comparison issues nothing: every ledger line comes back `cached` (R3).

**Decided.** Three, all about not producing a confident-looking empty table.

- **The sample is round-robin across creations, not a flat draw.** The creations differ in length by
  an order of magnitude, so a flat sample of ten would come almost entirely from the longest one. A
  model that handles verse and prose differently should be visible at M9, not at M12.
- **`compare` prints its plan and issues nothing without `--yes`** — the opposite default from `run`.
  `run` is aimed at a configuration whose cost has already been approved; `compare` multiplies that
  cost by the number of candidates, and profile extraction sends the whole configured corpus to every
  one of them.
- **A candidate that cannot be built is recorded, not raised.** With one key in hand, two candidates
  out of three failing to construct is the normal case, and stopping the comparison would mean the
  one that works is never measured. The failure appears in `summary.md` with the command that fixes
  it.

**Surprised by.** Nothing broke, which is worth writing down for a different reason: the module is
about 220 lines and almost all of it is composition — `select_sample` and the artifact writing are
the only new logic. Chunking, profile extraction, the rewrite request, the four validation checks,
FWED, the cache, the ledger and the runner were all reused as they stand. That the M9 harness could
be assembled rather than written is the return on M3 through M8 having been built as separable
pieces, and it is the strongest evidence so far that the architecture in `docs/ARCHITECTURE.md`
section 3 was worth the cost of the interfaces.

One thing it did make visible: the delta is **not** a quality score, and a table of deltas invites
reading it as one. A model that changes nothing scores near zero, a model that paraphrases freely
scores high, and neither is what the method wants. `summary.md` says so above the table, because the
person reading it at a meeting will not have read this file.

**Next.** Still the key. `pip install -e ".[gemini]"`, `GEMINI_API_KEY` into `.env`, then
`python -m mmlsa compare --config configs/mini.yaml -m gemini:gemini-2.5-flash --chunks 10`.

---

## 2026-08-16 (eighth) — CI had been red since M5, for one reason, and nobody looked.

**Goal.** Check whether CI passed on the M9 push. It had not — and neither had the four pushes
before it.

**Done.**
- `src/mmlsa/settings.py`: `RESERVED_ENV_VARS`, so `MMLSA_ALLOW_LIVE` is not parsed as a config key.
- `tests/unit/test_config.py`: a regression test for it, and one asserting a genuinely unknown
  `MMLSA_` key still raises, so the fix did not weaken I18.
- The documented quality gate is now `MMLSA_ALLOW_LIVE=0 pytest -q` in `CLAUDE.md`,
  `CONTRIBUTING.md` and `STATUS.md`.

**Verified.**
- The failing CI environment reproduced locally in one command:
  `MMLSA_ALLOW_LIVE=0 pytest tests/unit tests/contract tests/integration tests/data` — 30-plus
  failures and 21 errors before the fix, all green after.
- **CI run `31909369972` on `0659e98`: `check` success, `validation` success, every step.** The first
  green run this project has had.
- 593 tests pass locally with the variable set and without it.

**Decided.** The `MMLSA_` prefix serves two purposes — configuration overrides and process control —
and the loader now knows which names are which. Rejecting an unknown key stays the right behaviour
for a typo (I18); a reserved name is not a typo.

**Surprised by.** Three things, and the third is the one that matters.

1. **The bug was in the guard rail, not in the code it guards.** `MMLSA_ALLOW_LIVE` exists to stop
   tests reaching a real provider. Setting it broke every test that builds a configuration, because
   `env_overrides` collects every `MMLSA_*` variable and `canonical_key_path` correctly refuses a key
   that matches no field. Two correct behaviours, one collision.

2. **It was invisible locally by construction.** A developer's shell does not set the variable, so
   the suite ran in an environment CI never uses and CI ran in one no developer ever tested. Both
   were "the test suite passes" and only one of them was true.

3. **Five milestones were reported done on a red CI, and `CONTRIBUTING.md` requires "tests pass in
   CI" as clause 2 of its own definition of done.** `STATUS.md` carried "CI green pending first push"
   from M0 to M9 without anyone re-reading it after the first push happened. The rule this project
   already had — *never report a milestone as done without the command output that proves it* — was
   followed for the local suite and not for the thing the rule names. A gate nobody reads is not a
   gate. Checking CI is now part of the definition of done in prose, not just in principle.

**Next.** Unchanged: a key. `pip install -e ".[gemini]"`, `GEMINI_API_KEY` into `.env`, then the ten
rewrite calls of M9.

---

## 2026-08-16 (seventh) — M9 part one: the three live backends, still without a key.

**Goal.** M9's deliverable is a measured comparison of candidate models, which needs an API key we do
not have. Its prerequisite is code, which we do. Build the three backends the book names so the
milestone can start the moment a key exists, and keep every test offline (R5).

**Done.**
- `src/mmlsa/llm/providers/_live.py`: what the three share — keys from the environment at construction
  only, optional-SDK loading, HTTP-status failure classification, and the refusal of an empty
  completion.
- `src/mmlsa/llm/providers/{gemini,openai,anthropic}.py`, each with a model table.
- Registered all three; `PLANNED` and the "not until M9" error are gone.
- `tests/contract/test_live_providers.py`: 61 tests against stub SDKs registered in `sys.modules`.
- **Three configured-but-dead settings now do something.** `.env` was never loaded by anything, so a
  key placed where `README.md` says to put it would never have been seen; `llm.temperature` never
  reached a request; `llm.timeout_seconds` never reached a client.
- The dry run now plans against the configured model's real context window and names the model.

**Verified.**
- `pytest`: **592 passed** (was 527). `ruff check`, `ruff format --check`, `mypy src` all clean.
  98 per cent coverage on `llm/providers/`, 100 per cent on `_live.py`.
- Importing the registry imports no vendor SDK — checked in a subprocess, since it is a property of a
  fresh interpreter.
- Constructing any live provider without its key raises before any client is built.
- The dry run for the full corpus: 11 profile calls on a one-million-token model, **56** on a
  128,000-token one. Before this session both reported 11.

**Decided.** Three, recorded as `docs/DECISIONS.md` I24, I25 and I26: an empty completion is a
failure rather than an empty rewrite; each provider carries a model-capability table; the SDKs' own
retry loops are switched off because `Runner` owns retrying.

**Surprised by.** Four things, in ascending order of how quietly they would have hurt.

1. **`python-dotenv` was a declared dependency that nothing called.** `README.md` and `STATUS.md` both
   tell a new contributor to put their key in `.env`. Nothing read it. The first live call would have
   failed with "no API key" while the key sat in the file the documentation named — and the obvious
   next move, doubting the key, would have been the wrong one. `find_dotenv(usecwd=True)` matters
   here: the plain `load_dotenv()` searches from the *calling module's* directory, which for an
   installed package is not where the user is standing.

2. **The specification pins a parameter that several current models refuse.** `temperature = 0` is
   named in both `SPEC.md` and `PROMPTS.md`. Several current models — including the Anthropic ones we
   would compare — reject the parameter with a 400 rather than accepting and ignoring it, so a
   spec-faithful request is a failed request. Raised as `docs/OPEN_QUESTIONS.md` Q14 rather than
   absorbed. Worth noting that the book already anticipates the underlying problem in section 8 and
   prescribes the mitigation we are relying on: average over `M` runs, pin the version, log every call.

3. **Reasoning tokens are charged against the output budget.** On the current models `max_tokens`
   bounds the model's own deliberation *and* its answer together. A rewrite call with a 2,048-token
   budget can spend the lot thinking and return an empty string — and it is a successful HTTP 200.
   This is a configuration away from being the next item, which is the one that would really have hurt.

4. **An empty completion would have been the perfect false positive.** An empty rewrite shares no
   function words with its source, so FWED returns 1.0 — the maximum the metric can produce. A refusal,
   a safety block, or the budget exhaustion above would each have pushed a creation toward the
   suspicious set for a reason having nothing to do with its author, with no exception, no warning, and
   a perfectly healthy-looking run directory. That is the same shape as the `FakeProvider` bug in the
   entry below and the front-matter bug two entries below it: **the failures that matter in this
   project are the ones that produce a plausible number rather than an error.** It is now a recorded
   failure and the chunk is excluded.

**Next.** A key. `pip install -e ".[gemini]"`, `GEMINI_API_KEY` into `.env`, then
`python -m mmlsa run --config configs/mini.yaml --dry-run`, then ten rewrite calls read by hand
against `docs/TESTING.md` section 7 — above all, whether the model is quietly modernizing spelling,
which would inflate every delta uniformly and look like a working method while measuring nothing.

---

## 2026-08-15 (sixth) — M8: the orchestrator. The pipeline is finished.

**Goal.** Turn six steps into one command: the `M`-run loop, noise injection, and an immutable run
directory.

**Done.**
- `src/mmlsa/pipeline/noise.py`: deterministic selection of one foreign creation per run.
- `src/mmlsa/pipeline/orchestrator.py`: the run loop, the dry-run planner, and every artifact in
  `docs/ARCHITECTURE.md` section 6.
- `mmlsa run` now actually runs, with `--dry-run` and `--run-id`.
- `tests/unit/test_noise_selection.py`, `tests/integration/test_orchestrator.py`.

**Verified.**
- `pytest`: **527 passed**. `ruff`, `ruff format`, `mypy` all clean. 96 per cent coverage on the
  orchestrator, 100 per cent on noise selection.
- `python -m mmlsa run --config configs/mini.yaml` produces a run directory matching the documented
  layout file for file, including `noise_diagnostics.csv` listing exactly `M - 1` distinct creations.
- Two runs with the same config and seed produce byte-identical `scores.csv` in different
  directories, and the second issues zero provider calls.
- A completed run refuses to be overwritten; an interrupted one resumes.
- **The dry-run planner predicts the call count exactly**, asserted by test. That is what makes it
  safe to approve a wide job from the plan alone.

**Decided.**
- Chunking happens **once**, not once per run. Steps 2 and 4 have no model call and no randomness, so
  the chunks are identical across runs; re-chunking would imply a dependence that does not exist.
- A run is "complete" when its manifest records an end time. A directory without one is an
  interrupted run and may be resumed; one with it is a result and is never touched again.

**Surprised by.** Two things, both found by running the thing rather than by reasoning about it.

1. **`FakeProvider` returned a constant profile, which silently defeated noise injection.** The M7
   entry below predicted that the `M` runs would be identical without noise. They turned out to be
   identical *with* noise too: injecting a foreign creation changed the extraction prompt, so a new
   call was made, but the fake ignored its input and returned the same profile, so every rewrite
   prompt in run 2 was byte-identical to run 1 and hit the cache. The whole `M`-run apparatus ran and
   measured nothing, and the artifacts looked perfectly healthy.

   The fix is one line of intent: derive one figure in the fake profile from the prompt hash. Per-
   creation standard deviations are now non-zero and `test_the_runs_actually_differ` asserts it. The
   general lesson is that a test double which is *deterministic* is not automatically
   *discriminating*, and the difference is invisible until something downstream depends on it.

2. **`configs/poc.yaml` named five creations that do not exist.** It was written before the corpus
   was assembled, using identifiers like `macbeth` where the corpus has `the_tragedy_of_macbeth`. The
   dry run refused it. Had `load_corpus` silently ignored unknown identifiers — the obvious lenient
   choice — the proof of concept would have run on an empty subset and reported a threshold over
   nothing.

**Next.** M9, and it needs an API key. Everything that can be built offline is built.

---

## 2026-08-15 (fifth) — M7: Step 3, rewriting, and the pipeline closes

**Goal.** Build Step 3 and the response handling that protects the measurement, then wire all six
steps together to check the seams fit.

**Done.**
- `src/mmlsa/pipeline/rewrite.py`: cleaning (fences, preamble), the four specified validation checks,
  batched retries, per-creation failure accounting, and `to_chunk_deltas` as the seam into Step 5.
- `src/mmlsa/utils/text.py`: fence stripping, shared with Step 1 rather than duplicated.
- `tests/unit/test_rewrite_validation.py`: one test per pathological response.
- `tests/integration/test_pipeline_end_to_end.py`: all six steps over the mini corpus, no provider.

**Verified.**
- `pytest`: **488 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean. 96 per cent
  coverage on `rewrite.py`.
- Every pathological response named in `docs/TESTING.md` triggers its expected branch: empty,
  whitespace-only, fence-only, four refusal forms, half length, double length, full paraphrase,
  preamble, fence, fence-plus-preamble. And an unchanged copy of the input is **accepted**.
- The mini corpus runs end to end: three creations, two runs, 15 calls, a threshold with
  separability 0.893 and no flags.

**Decided.**
- Content retention is the **overlap coefficient over content-word types**, not Jaccard and not over
  tokens. Types because the question is whether the subject matter survived; overlap rather than
  Jaccard because a rewrite that legitimately adds a few words should not be penalised for the
  addition. Requiring token frequencies to survive would forbid the very rewriting the method asks
  for, since frequencies are the style signal.
- Retries are **batched by round** rather than serial per chunk, so concurrency survives a retry.

**Surprised by.** Two things, one a defect and one a hole in the test strategy.

1. **The preamble pattern in our own specification does not match "here's".** It reads
   `here (is|'s)`, with a space before the group, so it matches "here 's" and misses the contraction
   — which is the commoner of the two openings. Corrected in `docs/SPEC.md`, recorded as
   `DECISIONS.md` I23. What makes this worth dwelling on is the failure mode: an unstripped preamble
   does not raise anything. It is measured as part of the passage and inflates that chunk's delta,
   which is precisely the false positive the validation exists to prevent. A defect in the guard is
   worse than no guard, because it is invisible.

2. **With `FakeProvider` and no noise, the `M` runs are byte-identical by construction.** Same
   corpus gives the same profile, which gives the same rewrite prompts, which hit the cache. The
   end-to-end test duly reports a per-creation standard deviation of exactly zero. That is correct
   behaviour and not a bug, but it means run-to-run variation is currently exercised structurally
   and not numerically. **M8's tests must inject noise**, which is what makes the profile differ
   between runs offline. Noted in `docs/PLAN.md` under M8 so it cannot be forgotten.

Also worth recording: on the mini corpus the direction of the measurement is right. `mini_alpha`,
written with older function-word usage, scores lowest (0.0123); `mini_beta`, the same scene in modern
usage, scores highest (0.0413). `FakeProvider` substitutes modern forms for older ones, so a text
already in the older register needs the least change. That is a sanity signal, not a result.

**Next.** M8: the orchestrator, the `M`-run loop, deterministic noise selection, immutable run
directories, and `mmlsa run` actually running. `docs/PLAN.md` calls this the point at which the
pipeline is finished and everything after it is measurement.

---

## 2026-08-15 (fourth) — M6: Step 1, profile extraction

**Goal.** Build Step 1: take the whole corpus, pack it into as many calls as the context window
allows, extract a partial profile from each, and merge them into one.

**Done.**
- `src/mmlsa/prompts/`: the book's six templates as versioned files, plus rendering, profile
  serialization and the version map that feeds the cache key.
- `src/mmlsa/utils/tokens.py`: token estimation and deterministic first-fit-decreasing packing of
  whole creations.
- `src/mmlsa/pipeline/profile.py`: extraction, the merge call, structured parsing with a free-text
  fallback, and the per-run artifact record.
- `tests/fixtures/mini_corpus/`: three short locally authored texts, plus `mini_sources.yaml`, so
  `configs/mini.yaml` actually resolves. The loader now honours `corpus.dir` and supports texts with
  no Gutenberg origin.

**Verified.**
- `pytest -q`: **435 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean.
- All four M6 criteria: a merged profile with the six keys is produced from the mini corpus under
  `FakeProvider`; packing is identical across invocations and independent of input order; no
  creation is split across calls; every rendered pipeline prompt passes the neutrality scan.
- A built wheel contains all six templates and `versions.json`, so the prompts survive packaging.
- Real corpus: 1,437,851 estimated tokens, `k = 3` calls at a one-million-token window. Recorded as
  `docs/RESULTS.md` F-00b.

**Decided.**
- **Creation identifiers are not rendered into the extraction prompt.** The creations are numbered
  positionally and the packing record maps positions back to identifiers. A title is as much of a
  cue as an author's name, and this is the specific way a neutral template could have leaked.
- **An unparseable profile response falls back to free text rather than failing the run.** The
  book's literal form is free text anyway, so a formatting slip is not worth losing a run over. The
  fallback is logged so it is visible rather than silent.
- **Locally authored fixtures declare `gutenberg_id: null`.** Inventing identifiers for them would
  put numbers that look like provenance into the manifest.

**Surprised by.** The neutrality test found a leak in **our own code**, not in a template.

Two `src/` docstrings named a historical period: one in `utils/tokens.py` explaining why the token
estimate is conservative, one in `distance/tokenize.py` explaining why apostrophes survive. Both were
written as helpful context and both are exactly what R1 forbids, because the claim being defended is
that the method transfers to any author's corpus.

Worse, the forbidden-term list only caught one of them. It listed the three-word form of the period
name, so the two-word form went straight through. The list has been widened. The lesson is that a
guard rail is only as good as its list, and the list needs the *shortest* form of a term, not the
most complete one.

**Next.** M7, Step 3 rewriting: the chunk rewrite worker, preamble stripping, the four validation
checks and the retry policy. The templates exist already; what is missing is the response handling,
and that is where a refusal or a chatty preamble would otherwise become a large delta and manufacture
a false positive.

---

## 2026-08-15 (third) — M5: the LLM layer

**Goal.** Build the provider seam, the cache, the ledger and the runner, so that every later
milestone can be developed and tested without an API key.

**Done.**
- `src/mmlsa/llm/base.py`: `LLMRequest`, `LLMResponse`, the `LLMProvider` protocol, and the error
  taxonomy the runner reasons about (transient, permanent, cache miss).
- `cache.py`: content-addressed store, three modes (`live`, `replay`, `refresh`), atomic writes.
- `ledger.py`: append-only `calls.jsonl` with the full rendered prompt and response, a schema
  validator, and a summarizer.
- `runner.py`: bounded-concurrency execution, a token-bucket rate limiter for both the request and
  the token budget, `tenacity` retries with exponential backoff and full jitter, and deterministic
  result ordering by `(creation_id, chunk_index)`.
- `providers/`: `FakeProvider`, `ReplayProvider`, and a registry. The three live backends are
  deliberately absent until M9 and fail with a message naming that milestone.
- CLI: `mmlsa cache stats` and `mmlsa cache verify`.

**Verified.**
- `pytest -q`: **383 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean.
- Coverage on `src/mmlsa/llm/`: **97 per cent**.
- All six M5 acceptance criteria, individually:
  the contract suite passes for both providers; the same request twice issues one provider call;
  bumping `prompt_schema_version` forces a new call; `replay` mode raises on a miss; every ledger
  line validates and cache hits are logged too; and a run killed after 17 of 40 calls, restarted
  with the same run id, issues exactly 23, with a third invocation issuing none.

**Decided.**
- `prompt_schema_version` lives on the request, not in global configuration (`DECISIONS.md` I21), so
  editing one template invalidates only that template's entries rather than the whole cache.
- The cache key excludes `tag` (`DECISIONS.md` I22). The tag says what a call is for, not what was
  asked, and including it would charge twice for one answer.
- A cache write that loses a race is a success, not an error (`DECISIONS.md` I20).

**Surprised by.** Two things.

1. **Concurrency plus content addressing produces a genuine write race, and Windows fails it.**
   Identical prompts give identical keys by design — the same passage can occur in two creations,
   and every retry re-enters the same key — so parallel workers collide on one entry. The loser of
   the rename gets a `PermissionError`. Found by the ordering test, not in production, because that
   test happened to build jobs whose prompts did not vary by creation. The fix is small: if the
   destination exists afterwards, the write succeeded. The near miss is the interesting part — had
   the test used realistic prompts, this would have surfaced during the first wide run instead.

2. **How much of the design is load-bearing for resumability, and how little of it is code.** There
   is no checkpoint mechanism to test. Resume falls out entirely of consulting the cache before each
   call, which is why `docs/DECISIONS.md` I1 calls it the highest-leverage decision in the codebase.
   The resume tests are the only evidence that the property actually holds, so they are written
   against behaviour (call counts) rather than against implementation.

**Next.** M6, Step 1 profile extraction: token estimation, deterministic bin packing of whole
creations, `k` extraction calls and the merge call. Note that the corpus measures 1.065 million
words, so the multi-call path is the normal one, exactly as `docs/DECISIONS.md` I3 anticipated.

---

## 2026-08-15 (second half) — M2: the corpus

**Goal.** Assemble the 49-creation corpus and the three auxiliary sets, and make their integrity
checkable by a command.

**Done.**
- `data/corpus_sources.yaml`: all 49 creations with Gutenberg identifiers and the paper's own title
  for each, plus a 9-text noise pool, a 7-text held-out set and 3 mixture sources.
- `src/mmlsa/corpus/`: `gutenberg.py` (fetch, strict boilerplate stripping), `normalize.py` (ingest
  normalization and front-matter removal), `loader.py` (sources, disjointness, fetch, load),
  `manifest.py` (build and verify).
- CLI: `mmlsa corpus fetch` and `mmlsa corpus verify`.
- The 49 normalized creations and `data/manifest.json` are committed. Raw downloads are cached under
  `data/_raw/`, which is git-ignored.
- Tests: `test_normalization.py`, `test_manifest_verify.py`, `test_corpus_integrity.py`,
  `test_set_disjointness.py`.

**Verified.**
- `python -m mmlsa corpus verify`: **70 checks passed**, no warnings.
- 49 creations, **1,065,092 words**.
- `pytest -q`: **291 passed**. `ruff check`, `ruff format --check`, `mypy src` all clean.
- Milestone M3's two deferred corpus-wide properties now pass over the real texts: the full-coverage
  round trip at P = 200, 400 and 600, and `delta(x, x) == 0` over all 2,600-odd chunks, with zero
  degenerate chunks. M3 is closed.

**Decided.**
- **Which Gutenberg edition family.** The paper gives titles only. The 1500 series was reconstructed
  as the source because it is the only one containing every unusual entry in the paper's list
  (Pericles, The Rape of Lucrece, The Two Noble Kinsmen, Sir Thomas More, Locrine, Mucedorus). Where
  Gutenberg holds a duplicate, the entry matching the series' modernized format was taken, so an
  original-spelling quarto is not mixed into a modernized corpus. Raised as Q12.
- **Locrine and Mucedorus** are concatenated into one creation to preserve N = 49, matching the
  paper. Raised as Q13.
- **Noise texts must be creation-scale**, 10,000 to 60,000 words, enforced by a test. A noise text is
  added to the corpus *before* profile extraction, so The Faerie Queene at 472,000 words would have
  been a third of the corpus and would have rewritten the profile rather than perturbed it.

**Surprised by.** Four things, and the plan predicted the shape of all of them when it said this was
the milestone most likely to be underestimated.

1. **The paper has no Gutenberg identifiers at all.** `docs/DATA.md` assumed they were in it. They
   are not; it says only that the texts come from Gutenberg. The whole edition mapping had to be
   reconstructed and is now a documented assumption rather than a transcription.

2. **Two identifiers recalled from memory were simply wrong**, and checking every one against the
   Gutenberg catalogue caught both: 18268 is a Bliss Carman poetry collection, not Dekker's
   *Shoemaker's Holiday*, and 60287 is a Finnish novel, not *Gorboduc*. Neither would have failed
   loudly. They would have quietly become "foreign text" in a robustness experiment.

3. **Eyeballing the normalized files by hand found a real bug**, which is exactly what `docs/PLAN.md`
   said to budget time for. The scene lists and cast lists were surviving, because the first
   "ACT I" in these files is a contents entry rather than the play, and the rule was anchoring on
   it. Rewritten to anchor on the cast list, which sits between the contents and the body. It fires
   on 46 of 49; the three it skips are the poems, which have neither. 14,395 words of apparatus
   removed. **No test caught this** — `corpus verify` passed the whole time. Reading the files did.

4. **The corpus is 1.065 million words against a documented estimate of 0.9 to 1.0 million.**
   Measured rather than assumed or tolerated: speaker prefixes are 6.7 percent of it, stage
   directions 2.8, headings 0.6, and the spoken text is 956,416 words, inside the estimate. The
   sanity band was corrected to bound the quantity actually being measured. Recorded as `RESULTS.md`
   F-00, which also gives Q4 the number it previously lacked.

**Next.** M5: the provider protocol, cache, ledger and runner. Read `docs/ARCHITECTURE.md` section 4
first. `FakeProvider` has to produce non-trivial deterministic rewrites, or every downstream delta is
zero and the integration tests prove nothing.

---

## 2026-08-15 — Phase B kickoff: repository, environment, continuity docs

**Goal.** Turn the approved Phase A specification into a working repository and start the build.

**Done.**
- Cloned `eliranmeleh/Multi-Modal-LLM-Style-Analysis` (previously held only `book/` and
  `presentation/`) and copied the Phase B specification kit into it: `CLAUDE.md`, `docs/` (13 files),
  `configs/` (7 files), `pyproject.toml`, `.github/workflows/ci.yml`, `.gitignore`, `.env.example`,
  `LICENSE`, `CITATION.cff`, `CONTRIBUTING.md`.
- Added the continuity documents: `docs/STATUS.md` (live board), this file, and `docs/MEETINGS.md`.
- Provisioned Python 3.11 through `uv` into `.venv`.
- Created the package skeleton `src/mmlsa/` with the Typer entry point.

- Built **M0** (package skeleton, Typer CLI, test layout, CI fixes), **M1** (config model, `extends`
  resolution, config hashing, four-layer precedence, structured logging), **M3** (chunking, the
  function-word tokenizer, FWED with the private-use-area sequence Levenshtein, the distance
  registry, the versioned 127-entry word list) and **M4** (aggregation, exact Otsu, the `skimage`
  cross-check, a Gaussian-mixture fallback, bimodality diagnostics, `scores.csv`, `threshold.json`
  and the three figures).
- 227 tests, written before or alongside each implementation.

**Verified.**
- `docs/SPEC.md` checked line by line against the approved book
  (`Project_Book_Phase_A.docx`, 17 July 2026): sections 4.1, 4.3, 4.6, 4.7, 4.8, 4.9, and the two
  prompt templates in 5.2. No drift found. The spec is a faithful transcription and remains the
  contract.
- `ruff check .`, `ruff format --check .` and `mypy src` all clean.
- `pytest -q`: 227 passed. Coverage 91 percent overall; on the modules where a bug is silent,
  `tokenize` and `score` at 100, `chunking` 95, `fwed` 95, `classify` 92.
- `python -m mmlsa config validate`: all seven shipped configs resolve, including the two-level
  `extends` chains.
- `python -m mmlsa run --config configs/poc.yaml --dry-run` resolves and prints the plan without
  touching data.

**Decided.**
- Python 3.11 is provisioned with `uv` rather than relaxing `requires-python` to admit the machine's
  system 3.12. The book's tools table names 3.11 and examiners read it, so the environment matches the
  document instead of the document being edited to match the machine. Recorded as `DECISIONS.md` I19.
- Provider order: Gemini first, on the free tier, because it has the largest context window (the
  profile step packs whole creations) and the book names it first among the candidates. `llm.provider`
  is one config key, so the eventual model-choice decision at M9 costs nothing to change.
- Override keys are matched against the model's field names case-insensitively (`DECISIONS.md` I18).
  Found by a failing test: `MMLSA_RUN__M` was being lowercased to `run.m`, and the two specified keys
  that are single uppercase letters, `chunking.P` and `run.M`, were therefore unreachable from the
  environment. Unknown override keys now raise instead of being ignored.
- The book's visual bimodality check is also computed numerically (`DECISIONS.md` I17), as Otsu's
  separability and the gap at the split in standard deviations. Both are config keys, not constants.

**Surprised by.** Three things, all recorded rather than patched over.

1. **The function-word list has no wh-adverbs.** `when`, `where`, `why`, `how` are absent from the
   v1 composition in `docs/DATA.md` section 5.1, although `while`, `since` and `then` are present.
   The documentation's own worked example in section 5.3 assumed `when` was in the list and gave
   `3/7 = 0.4286`; the list as specified gives `3/6 = 0.5`. The example was corrected to match the
   list, because 5.1 is the normative text and the list is versioned for exactly this reason.
   Raised as `OPEN_QUESTIONS.md` Q10. **This must be settled before M10** — changing the list changes
   every delta ever computed.

2. **The Otsu cross-check cannot compare the two thresholds numerically**, which is what the spec
   asks for. Both implementations pick the same split but report `tau` at different points inside the
   gap: the exact form at the midpoint, `skimage` at the centre of the last bin below the split. The
   difference is half the gap width, so a *cleaner* separation looks like a *worse* disagreement. The
   check now compares which gap the two split at. Raised as `OPEN_QUESTIONS.md` Q11.

3. **The binned threshold really does move a label.** On a clean two-cluster example, `skimage`
   returns a value fractionally below the largest lower-class score, which pushes that creation into
   the suspicious set. This is direct empirical support for `DECISIONS.md` I2 and is worth a sentence
   in the Phase B report: with 49 points, `nbins` is not a harmless default.

**Next.** M2. Extract the 49 titles and Gutenberg identifiers from `fqaf009.pdf` into
`data/corpus_sources.yaml`, then fetch, normalize and build the manifest. Then close out M3 by
re-running its two corpus-wide properties over the real texts.
