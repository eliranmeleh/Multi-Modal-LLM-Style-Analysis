# CONTRIBUTING

The team's working agreement. `CLAUDE.md` covers how an AI coding agent should behave in this
repository; this file covers how the two of us work.

---

## Working through issues

Agreed in #5 on 2026-11-24. Issue and pull request comments are our shared record, so they stay
short, factual and in English.

1. **Every task is an issue.** A finding, a question or a piece of work for the other person becomes
   an issue, not a chat message.
2. **Taking a task.** Before starting, assign the issue to yourself and comment that you started, so
   we never work on the same thing twice. If the other person objects in a comment, the work stops
   until we agree.
3. **One branch per issue**, named `<eliran|miron>/<issue-number>-<short-slug>`, and a pull request
   whose description says `Closes #<number>`.
4. **Nobody merges their own pull request alone.** The other person reviews first. The author merges
   after the approval, or the reviewer merges when the author asked for it.
5. **Numbered points with a mark**, in issues and reviews alike:
   - `[fix]`: a factual or wording change the pull request's author may just make and push; it is
     still reviewed in the pull request.
   - `[decision]`: belongs to both of us. Nobody acts on it until we have both answered.
   - `[question]`: needs an answer, such as where a fact or a number comes from.

   Replies go point by point with the same numbers: what changed (with the commit) or why not.
6. **Never push to the other person's branch or to `main`.** A change to someone else's pull request
   is a review comment.
7. **Record decisions where they are made**: who decided, the date, and a link to the comment. A
   supervisor decision also goes to `docs/DECISIONS.md` the same day.

## Branching

- `main` is always green. Never commit to it directly.
- One branch per issue, as above. A milestone usually spans several issues, so name the milestone in
  the issue rather than in the branch.
- One branch per experiment run that changes code, also through its issue.
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
