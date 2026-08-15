# PROMPTS

The prompt templates are part of the approved specification (project book section 5.2) and are reproduced
here verbatim. They live in `src/mmlsa/prompts/*.txt` as template files, never as string literals inside
logic, so that they are reviewable, diffable and hashable.

---

## 0. Rules that apply to every prompt

1. **Neutrality.** No prompt in the pipeline may contain the target author's name, a period label
   ("Elizabethan", "Early Modern"), a genre cue, or any other hint that would let the model fall back on
   a memorized prior. This is what makes the method unsupervised and transferable, and it is the single
   most important property to preserve. `tests/unit/test_prompt_neutrality.py` asserts it by scanning the
   rendered prompts against a forbidden-term list.
   **The one exception** is the control experiment's Mode B prompt, whose entire purpose is to invoke the
   memorized prior. Its author name comes from `config.corpus.author_label`, never from source code.

2. **Versioning.** Every template file carries a `prompt_schema_version` recorded in
   `src/mmlsa/prompts/versions.json`. The version is part of the cache key, so editing a template
   invalidates exactly the affected cache entries and nothing else. Never edit a template without
   bumping its version.

3. **Rendering is deterministic.** Templates use `string.Template` with explicit placeholders. The
   rendered prompt is hashed and stored in the ledger. Given the same config and inputs, byte-identical
   prompts are produced on every machine.

4. **Generation parameters.** `temperature = 0`, model version pinned, no penalties, no top-p tuning.
   Recorded per call.

---

## 1. Style-profile extraction

Sent once per profile-packing call, per run. Placeholder `$creations` is filled with the full text of
each creation in that call's bin, in the order produced by the deterministic packing.

**`prompts/profile_extract.txt`** (verbatim from the approved book):

```
Analyze the dominant writing style in the following creations.
Describe quantitative patterns you observe in:
- Word choice and vocabulary preferences
- Pronoun usage patterns
- Verb forms and conjugations
- Sentence structure and length
- Punctuation habits
- Any other distinctive linguistic features
Be specific and quantitative where possible.

$creations
```

`$creations` renders as:

```
Creation 1: <full text of creation #1>

Creation 2: <full text of creation #2>

...
```

**Structured-output suffix.** When `profile.structured_output: true` (the default), the following block
is appended. It adds no new instruction: the keys are the six bullets already in the prompt. Set the flag
to `false` for the book's literal free-text form.

```
Return your answer as a single JSON object with exactly these string keys:
"vocabulary", "pronouns", "verb_forms", "sentence_structure", "punctuation", "other".
```

## 2. Profile merge

Used only when the corpus was packed into more than one extraction call. Not in the book, which specifies
the split but leaves the consolidation implicit. Justified in `docs/DECISIONS.md`, flagged for supervisor
confirmation in `docs/OPEN_QUESTIONS.md`.

**`prompts/profile_merge.txt`**:

```
Below are several independent stylistic analyses of different parts of one body of work.
Consolidate them into a single coherent style description.

Rules:
- Keep only patterns that are consistent across the analyses.
- Where the analyses disagree, state the dominant tendency and note the variation.
- Do not introduce any observation that is not supported by the analyses below.
- Do not name any author, period, or literary tradition.

Return your answer as a single JSON object with exactly these string keys:
"vocabulary", "pronouns", "verb_forms", "sentence_structure", "punctuation", "other".

$partial_profiles
```

## 3. Chunk rewriting (Mode A, the method)

Sent once per chunk per run. `$profile` is the run's merged profile, serialized deterministically;
`$passage` is the chunk text exactly as stored.

**`prompts/rewrite.txt`** (verbatim from the approved book):

```
Here is a style profile of a target author:
$profile

Rewrite the following passage to match this style profile exactly.
Preserve the meaning and content - only transform stylistic features
(word choice, sentence structure, function words, punctuation).
Do not paraphrase or change content words.

Passage to rewrite:
$passage
```

**Profile serialization.** With structured output on, render the JSON as stable labelled lines
(`Vocabulary: ...`, `Pronouns: ...`, and so on) in fixed key order. Never dump raw JSON into the rewrite
prompt: it changes the register of the instruction, and key ordering would leak nondeterminism into the
cache key.

**Output contract.** The model must return only the rewritten passage. Add nothing to the template to
enforce this. Preamble handling is done in post-processing (`docs/SPEC.md`, Step 3), because changing the
prompt would deviate from the approved text.

## 4. Rewrite retry suffix

Appended to the same rewrite prompt on a content-validation failure. Each retry is a separate cache entry
because the prompt differs.

**`prompts/rewrite_retry.txt`**:

```

Important: return only the rewritten passage, with no introduction, no explanation,
and no surrounding quotation marks or code fences. Keep the same content and
approximately the same length as the passage above.
```

## 5. Control experiment, Mode B

The generic-prompt arm of the control experiment. Its purpose is precisely to test whether the extracted
profile contributes anything beyond the model's memorized prior, so here the author name is required.

**`prompts/rewrite_generic.txt`**:

```
Rewrite the following passage in $author_label's style.
Preserve the meaning and content - only transform stylistic features
(word choice, sentence structure, function words, punctuation).
Do not paraphrase or change content words.

Passage to rewrite:
$passage
```

`$author_label` comes from `config.corpus.author_label`. No author name appears in `src/`.
Mode A and Mode B run over the **same chunks** so that the t-test is genuinely paired.

## 6. Storage and audit

- Templates: `src/mmlsa/prompts/*.txt`, packaged with the distribution.
- Versions: `src/mmlsa/prompts/versions.json`, mapping template name to integer version.
- Every rendered prompt is written in full to `runs/<run_id>/calls.jsonl` together with its response.
  The book commits the project to publishing prompts, and this is how that commitment is met at the
  level of the actual bytes sent, not just the templates.
