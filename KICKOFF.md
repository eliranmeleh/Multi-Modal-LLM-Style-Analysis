# KICKOFF

How to use this kit, and the exact prompts to open with.

> **Part 1 is complete.** The repository is set up, the specification is in place, and the build has
> started. For where the implementation currently stands, read `docs/STATUS.md`. For the
> start-of-session and end-of-session routine, read `CLAUDE.md` section 0. Part 1 below is kept only
> as a record of how the repository was assembled.
>
> Parts 3 to 6 are still live: they are the per-milestone prompt shape and the working habits.

---

## Part 1 — Setting up the repository (done)

1. Clone the project repository:
   ```bash
   git clone https://github.com/eliranmeleh/Multi-Modal-LLM-Style-Analysis.git
   cd Multi-Modal-LLM-Style-Analysis
   ```

2. Copy the **entire contents** of this kit into the repository root, preserving the structure.
   Note the dot-files: on Windows, `copy` and drag-and-drop skip hidden entries, so verify that
   `.github/`, `.gitignore` and `.env.example` actually arrived.
   ```
   CLAUDE.md  README.md  CONTRIBUTING.md  CITATION.cff  LICENSE
   KICKOFF.md              (optional; a working note, not a deliverable)
   pyproject.toml  .gitignore  .env.example
   .github/                (workflows/ci.yml, PULL_REQUEST_TEMPLATE.md)
   configs/                (default, mini, poc, sensitivity, full, control, purification)
   docs/                   (SPEC, ARCHITECTURE, DATA, PROMPTS, PLAN, EXPERIMENTS,
                            TESTING, DECISIONS, OPEN_QUESTIONS, GLOSSARY,
                            TRACEABILITY, RUNBOOK, RESULTS)
   ```

   Thirty-one files in total. Verify the count after copying; a silently skipped dot-directory is the
   usual cause of a red first CI run.

3. Commit them as the project's starting point:
   ```bash
   git add -A
   git commit -m "Add Phase B specification, architecture and implementation plan"
   git push
   ```

4. Open Claude Code in the repository root. It reads `CLAUDE.md` automatically.

**Before writing any code**, do the one task no tool can do for you: open the reference paper
(`fqaf009.pdf`), find the list of the 49 texts and their Project Gutenberg identifiers, and write them
into `data/corpus_sources.yaml`. Every downstream comparison depends on using the same corpus.

## Part 2 — The opening prompt

Paste this as the first message of the first session.

> This repository implements the Phase B software for an approved academic capstone project. The method
> is already specified and approved; do not redesign it.
>
> Read `CLAUDE.md`, then `docs/SPEC.md`, then `docs/ARCHITECTURE.md`, then `docs/PLAN.md`.
>
> Then do three things, and nothing else yet:
>
> 1. Tell me in your own words what the method does in six steps, so I can confirm you understood it.
> 2. List anything in the specification that you think is ambiguous or impossible to implement as
>    written. Do not fix anything, just list it, and compare your list against `docs/OPEN_QUESTIONS.md`
>    so I can see what is already known.
> 3. Restate the acceptance criteria for milestone M0 from `docs/PLAN.md`.
>
> Do not write any code in this message. Wait for my confirmation.

The three questions are the point. If the restatement of the method is wrong, everything built afterwards
is wrong in the same way, and it is far cheaper to catch it here. The second question surfaces genuine
specification gaps early rather than as silent assumptions buried in code.

## Part 3 — The per-milestone prompt

Use this shape for every milestone. Working one milestone at a time is what keeps the code reviewable.

> Implement milestone **M<n>** from `docs/PLAN.md`.
>
> Before writing code: restate the acceptance criteria and tell me which files you will create or change.
> Wait for my go-ahead.
>
> Then implement it, following `docs/ARCHITECTURE.md` for structure and `docs/SPEC.md` for behaviour.
> Write the tests specified in `docs/TESTING.md` for this milestone **first**, then the implementation.
>
> When the acceptance criteria pass, show me the test output, tick the checkbox in `docs/PLAN.md`, and
> add any new ambiguity you hit to `docs/OPEN_QUESTIONS.md`. Then stop, so I can review before the next
> milestone.

## Part 4 — Prompts worth having ready

**When something in the spec looks wrong.**

> You flagged an issue with the specification. Do not fix it in code. Add it to
> `docs/OPEN_QUESTIONS.md` with the question, your recommended interim behaviour, and who needs to
> resolve it. Then implement the specification-faithful behaviour, putting the workaround behind a config
> flag if one is needed.

**Before any expensive run.**

> Run `--dry-run` first and report the exact number of LLM calls, the token estimate and the expected
> wall clock. Do not issue any real request until I approve the number.

**Reviewing your own work at the end of a milestone.**

> Review what you just wrote against `docs/SPEC.md` and `CLAUDE.md`. Check specifically: no author name
> in `src/`, every LLM call goes through the cache and the ledger, no magic numbers outside config,
> every public function annotated, and every deterministic function unit-tested. Report what fails
> before I look at it.

**When results do not separate.**

> The proof-of-concept scores do not separate the known cases. Before changing any parameter, work
> through the diagnostic list in `docs/EXPERIMENTS.md` under Stage 1 and tell me which explanation the
> evidence supports. Do not tune anything until we know why.

## Part 5 — Working habits worth keeping

- **One milestone per session.** Long sessions drift away from the plan.
- **Review the diff before every commit.** A generated file that no one reads is a liability in a graded
  repository.
- **Never let a number reach the report by hand.** Generate the tables from the run artifacts.
- **Keep `docs/OPEN_QUESTIONS.md` alive.** It is the agenda for the next supervisor meeting.
- **Commit messages describe the change, plainly.** Nothing about tooling or assistance. The repository
  history is read by examiners and is attributed to the students.
- **Run `--dry-run` before anything wide.** A full run is roughly 7,500 calls.

## Part 6 — The first three sessions, concretely

| Session | Goal | Ends when |
|---------|------|-----------|
| 1 | M0 and M1: skeleton, config, logging, CI | `python -m mmlsa --help` works and CI is green |
| 2 | M2: corpus acquisition, normalization, manifest | `python -m mmlsa corpus verify` passes on all 49 texts |
| 3 | M3: chunking, tokenizer, FWED, with tests written first | Golden test and all properties pass on the real corpus |

After session 3 there is a real, tested, offline measurement tool. Only then is it worth connecting a
model.
