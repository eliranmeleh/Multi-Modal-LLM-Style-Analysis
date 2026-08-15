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
