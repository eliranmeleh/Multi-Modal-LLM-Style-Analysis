# CONTRIBUTING

The team's working agreement. `CLAUDE.md` covers how an AI coding agent should behave in this
repository; this file covers how the two of us work.

---

## Branching

- `main` is always green. Never commit to it directly.
- One branch per milestone: `m03-chunking-fwed`, `m07-rewrite-worker`.
- One branch per experiment run that changes code: `exp-control-sample`.
- Rebase onto `main` before opening a pull request. Keep history linear.

## Pull requests

Every change reaches `main` through a pull request, even with a team of two. Reading each other's diff
is the cheapest quality control available, and the repository history is read by the examiners.

The template in `.github/PULL_REQUEST_TEMPLATE.md` asks four questions. Answer them honestly, including
"no" where the answer is no.

**Reviewer checklist:**

- [ ] The milestone's acceptance criteria in `docs/PLAN.md` are actually met, not approximately met.
- [ ] Behaviour matches `docs/SPEC.md`. Any deviation is documented in `docs/OPEN_QUESTIONS.md`.
- [ ] Deterministic functions have unit tests with exact expected values, not smoke tests.
- [ ] No author name anywhere in `src/`.
- [ ] No magic numbers. Anything tunable is a config key.
- [ ] No secret, no `.env`, no cache directory, no large binary in the diff.
- [ ] Commit messages read professionally and say nothing about tooling.

## Commits

- Imperative mood, plain professional English: `Add exact Otsu thresholding with skimage cross-check`.
- One logical change per commit. A commit that both refactors and adds a feature is two commits.
- **Never mention AI assistance, generation, or editorial cleanup** in a message, a comment, or any file.
  All authorship is attributed to the two of us. No `Co-Authored-By` trailers.
- Reference the milestone where it helps: `M4: add borderline banding around tau`.

## Definition of done

A milestone is done when **all** of the following hold. Not four of five.

1. The acceptance criterion in `docs/PLAN.md` passes and the output is pasted into the pull request.
2. Tests for the milestone exist and **pass in CI** — checked on the CI run, not inferred from a green
   local run. Run the suite as `MMLSA_ALLOW_LIVE=0 pytest -q`, which is the environment CI uses.
3. `ruff check`, `ruff format --check` and `mypy src` are clean.
4. The checkbox in `docs/PLAN.md` is ticked.
5. Anything ambiguous encountered along the way is written into `docs/OPEN_QUESTIONS.md`.

## Before running anything expensive

1. `--dry-run` first. Read the call count and the token estimate.
2. Tell the other person the number before starting.
3. Confirm `llm.model_id` is a pinned snapshot, not a floating alias.
4. Confirm the seed is the one you intend to publish.

## Adding a dependency

Do not, unless it is genuinely needed. The approved book lists the toolchain and examiners read that
table. If you must, add a row to `docs/DECISIONS.md` with the reason and add it to `pyproject.toml` in
the same commit.

## Recording results

Findings go into `docs/RESULTS.md` as they happen, not at the end. Every number there points to a
committed run directory. Never retype a number by hand into a document: generate it.
