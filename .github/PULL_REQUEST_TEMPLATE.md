## What and why

<!-- One or two sentences. Which milestone from docs/PLAN.md, or which experiment. -->

## Acceptance criteria

<!-- Paste the criterion from docs/PLAN.md, then the evidence: test output, a table, a figure. -->

- [ ] Criterion met, evidence below

```
<paste test output here>
```

## Specification

- [ ] Behaviour matches `docs/SPEC.md`
- [ ] Any deviation is documented in `docs/OPEN_QUESTIONS.md` (not silently in code)
- [ ] Any new engineering decision is recorded in `docs/DECISIONS.md`

## Guard rails

- [ ] No author name in `src/`
- [ ] No magic numbers outside `configs/`
- [ ] Every LLM call goes through the cache and the ledger
- [ ] No secret, `.env`, cache directory or large binary in this diff
- [ ] `ruff`, `mypy` and `pytest` are clean

## Anything surprising

<!-- What did not behave as expected. Write "nothing" if nothing did. This field is where the
     real information usually is, so do not leave it empty out of politeness. -->
