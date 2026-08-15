# CLAUDE.md

Operating manual for AI coding agents working in this repository.
Read this file first, then `docs/SPEC.md`, then the milestone you are working on in `docs/PLAN.md`.

---

## 0. Session protocol

This project runs over many sessions with no shared memory between them. Three files carry that
memory, and keeping them current is part of the work, not paperwork after it.

**At the start of every session, in this order:**

1. `docs/STATUS.md` — where we are, what is next, what is blocked. One page. Read it first, always.
2. The last entry of `docs/SESSION_LOG.md` — what happened last time and *why*, especially the
   **Surprised by** line, which is where the expensive knowledge lives.
3. The milestone you are about to work on in `docs/PLAN.md`, and its acceptance criteria.

Then restate the acceptance criteria back to the user before writing any code.

**At the end of every session, before you stop:**

1. Update `docs/STATUS.md` in place: the milestone board, the next actions, the blocked list.
   A milestone becomes **done** only when its acceptance criterion demonstrably passes. If it is
   half-done, write the half.
2. Append an entry to `docs/SESSION_LOG.md` using the template at the top of that file. It is
   append-only; never edit or delete a past entry.
3. Anything that needs a supervisor decision goes to `docs/OPEN_QUESTIONS.md`, and onto the agenda
   in `docs/MEETINGS.md`.
4. Anything measured goes to `docs/RESULTS.md` with the run id that produced it.

**Never report a milestone as done without the command output that proves it.** "It should work" is
not a verification, and in a project whose output is a number, an unverified claim is worse than an
admitted gap.

---

## 1. What this project is

`mmlsa` (Multi-Modal LLM Style Analysis) implements an unsupervised, zero-shot authorship-anomaly
detection pipeline. A large language model extracts a generic style profile from a corpus, rewrites
every chunk of every text under that profile, and the size of the required rewrite (a *style distance*)
becomes the detection signal. Texts that barely change are authentic; texts that change a lot bear
another hand.

The running corpus is the 49 creations attributed to Shakespeare. The method is author-agnostic.

This is a graded academic capstone project (Braude College, project code 26-2-R-6). Phase A produced a
fully specified method, reviewed and approved by the supervisors. **Phase B is implementation.**
The specification is frozen. Your job is to implement it faithfully, not to redesign it.

## 2. The single source of truth

`docs/SPEC.md` is a transcription of the approved Phase A project book. It is the contract.

**If code and `docs/SPEC.md` disagree, the spec wins and the code is a bug.**

If you believe the spec is wrong, incomplete, or impossible to implement as written:
1. Do not silently deviate.
2. Write the issue into `docs/OPEN_QUESTIONS.md` with your recommendation.
3. Implement the spec-faithful behaviour behind a config flag if a workaround is needed.
4. Say so in your reply to the user.

Design decisions that are already settled are recorded in `docs/DECISIONS.md`. Do not relitigate them.

## 3. Hard rules

These are non-negotiable. Each maps to a non-functional requirement in the approved book.

| # | Rule | Why |
|---|------|-----|
| R1 | **No author name is hard-coded in `src/`.** The strings "Shakespeare", "Hamlet", "Macbeth" and any other corpus-specific identifier live only in `data/`, `configs/`, `tests/fixtures/` and `docs/`. | NFR Generalizability. Enforced by `tests/test_no_hardcoded_author.py`. |
| R2 | **Every LLM call is logged** to the run ledger with prompt, response, model id, model version, parameters, token usage, latency and UTC timestamp. | NFR Auditability. |
| R3 | **Every LLM call goes through the cache.** No direct provider calls from pipeline code. | Reproducibility, resumability, and re-runs cost nothing. |
| R4 | **The provider is selected by one config key.** Adding a provider must not touch pipeline code. | NFR Modularity. |
| R5 | **Tests never hit a real API.** Only `FakeProvider` or `ReplayProvider`. CI has no API keys. | Deterministic CI. |
| R6 | **No secret ever reaches a file, a log line or a commit.** Keys come from environment variables only. `.env` is git-ignored. | Public repository. |
| R7 | **Every score is traceable** from the final per-creation number back to the individual chunk deltas and the exact LLM calls that produced them. | NFR Interpretability. |
| R8 | **Randomness is seeded and recorded.** Any sampling, shuffling or noise-creation selection uses the run seed from config. | Reproducibility. |
| R9 | **Run artifacts are immutable.** Never overwrite a completed `runs/<run_id>/` directory. New parameters mean a new run id. | Auditability. |

## 4. Repository conventions

- **Language:** Python 3.11 (fixed by the approved book).
- **Package root:** `src/mmlsa/`, installed as an editable package. Import as `from mmlsa... import ...`,
  never by relative path manipulation.
- **Entry point:** one CLI, `python -m mmlsa <command>` (Typer). No ad-hoc scripts in the repository root.
- **Config:** one YAML file validated by a Pydantic model. No magic numbers in code. If a value could
  reasonably change, it belongs in config.
- **Typing:** all public functions are annotated. `mypy` runs in CI in non-strict mode.
- **Formatting and linting:** `ruff format` and `ruff check`. Line length 100.
- **Docstrings:** one-line summary for every public function; full docstring where the maths is non-obvious,
  citing the spec section (for example `See docs/SPEC.md section 4.6.3`).
- **Errors:** fail loudly and early on bad configuration. Never swallow an exception from a provider without
  recording it in the ledger.
- **Logging:** `structlog` or stdlib `logging` with a JSON formatter. Never `print()` outside the CLI layer.

## 5. Data flow you must preserve

```
corpus (49 texts)
  -> [Step 1] profile extraction        LLM, corpus-level, once per run
  -> [Step 2] chunking                  deterministic, no LLM
  -> [Step 3] rewrite                   LLM, once per chunk per run
  -> [Step 4] style distance            deterministic, no LLM
  -> [Step 5] aggregation               mean over chunks, then mean over runs
  -> [Step 6] threshold classification  deterministic, no LLM
```

Steps 2, 4, 5 and 6 contain **no** LLM calls and must be unit-testable without a provider.
Keep that separation: it is what makes the project testable.

## 6. Working style expected of you

- **Small, reviewable commits.** One milestone task per commit.
- **Test first where behaviour is deterministic** (chunking, distance, Otsu, tokenization).
  These have exact expected values in `docs/TESTING.md`.
- **Before writing code for a milestone**, restate the acceptance criteria from `docs/PLAN.md`
  and confirm you are implementing the right thing.
- **After a milestone**, update its checkbox in `docs/PLAN.md` and note anything surprising in
  `docs/OPEN_QUESTIONS.md`.
- **Do not add dependencies** beyond those listed in `docs/ARCHITECTURE.md` without saying why.
  The approved book names the toolchain and examiners read it.
- **Never run a full-corpus job without being asked.** A full run is roughly 7,500 LLM calls.
  Default every command to a small subset and require an explicit flag to go wide.

## 7. Commit and repository hygiene

This repository is a graded, public academic artifact and its history is read by examiners.

- Commit messages describe the change in plain professional English. Imperative mood, no emoji.
- **Never mention AI assistance, "generated by", or editorial cleanup in a commit message,
  a code comment, or any file in the repository.** Attribute all authorship to the students.
- No `Co-Authored-By` trailers.
- Do not commit: `.env`, `cache/`, raw API responses containing keys, large binary artifacts,
  or the `.venv`.

## 8. Quick commands

```bash
uv sync                       # or: pip install -e ".[dev]"
python -m mmlsa --help
python -m mmlsa corpus verify                     # data integrity
python -m mmlsa run --config configs/poc.yaml     # small subset, real provider
python -m mmlsa run --config configs/poc.yaml --provider fake   # no API calls
python -m mmlsa report --run-id <run_id>

# The quality gate. Set MMLSA_ALLOW_LIVE=0: CI sets it on every run and your shell does not,
# so without it the suite runs in a different environment locally than it does on CI.
MMLSA_ALLOW_LIVE=0 pytest -q
ruff check . && ruff format --check . && mypy src
```

## 9. Where to look

| Question | File |
|----------|------|
| What exactly does the method do? | `docs/SPEC.md` |
| How is the code organised? | `docs/ARCHITECTURE.md` |
| Where does the corpus come from and how is it cleaned? | `docs/DATA.md` |
| What is the exact prompt text? | `docs/PROMPTS.md` |
| What do I build next? | `docs/PLAN.md` |
| How is the method validated? | `docs/EXPERIMENTS.md`, `docs/TESTING.md` |
| Why was it done this way? | `docs/DECISIONS.md` |
| What is still undecided? | `docs/OPEN_QUESTIONS.md` |
| What does this symbol or term mean? | `docs/GLOSSARY.md` |
| Where is requirement X implemented? | `docs/TRACEABILITY.md` |
| How do I run, monitor or recover a long job? | `docs/RUNBOOK.md` |
| What have we measured so far? | `docs/RESULTS.md` |
| How does the team work (branches, PRs, done)? | `CONTRIBUTING.md` |

Two documents are **written to**, not only read: record every finding in `docs/RESULTS.md` as it
happens, and every ambiguity in `docs/OPEN_QUESTIONS.md`. Update `docs/TRACEABILITY.md` whenever a
module or a test that implements a requirement moves.
