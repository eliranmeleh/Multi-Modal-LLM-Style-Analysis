# DATA

Corpora, acquisition, normalization, the function-word list, and the integrity rules that protect the
validity of the experiments.

---

## 1. The four text sets

| Set | Directory | Size | Purpose |
|-----|-----------|------|---------|
| **Target corpus** | `data/corpus/` | 49 texts | The creations attributed to the target author. Profiled, chunked, scored, classified. |
| **Noise pool** | `data/noise_pool/` | at least `M - 1`, aim for 10 | Foreign texts. One is injected per run from run 2 onward. |
| **Held-out set** | `data/heldout/` | 6 to 10 | Confirmed in-corpus and known out-of-corpus texts, reserved before the pipeline is finalized. |
| **Mixture sources** | `data/mixture_sources/` | 3 to 5 | Foreign passages spliced into pure texts at known positions. |

### 1.1 Integrity rules (enforced by `tests/data/test_set_disjointness.py`)

1. **No text id appears in more than one set.** A text used as noise must never also be a held-out test
   subject, and a text spliced in the mixture test must never be in the noise pool. Violating this turns
   a validation test into a self-fulfilling result.
2. **The held-out set is reserved before the pipeline is finalized** and is not looked at during
   development. Record the date it was fixed in `data/manifest.json`.
3. **Prefer disjoint authors between the noise pool and the held-out set.** Text-level disjointness is
   the hard rule; author-level disjointness is a strong preference, because a profile perturbed by
   Marlowe in run 2 is not an unbiased judge of a different Marlowe text later.
4. Every file has a recorded `sha256`. `python -m mmlsa corpus verify` fails if any checksum drifts.

## 2. Building the target corpus

**Source:** Project Gutenberg, the same 49 texts used by the prior study on this corpus, so that results
are directly comparable.

**First implementation task, before any code:** extract the exact list of 49 titles and their Gutenberg
identifiers from the reference paper (appendix / results table) and record it in
`data/corpus_sources.yaml`. Do not guess the list, and do not substitute a different edition.
Comparability with the published findings is a success metric, and it fails silently if the corpus differs.

`data/corpus_sources.yaml` schema:

```yaml
author_label: shakespeare          # used only for output labels, never for logic
texts:
  - id: hamlet
    title: "Hamlet"
    gutenberg_id: 1524
    url: "https://www.gutenberg.org/ebooks/1524"
    expected_words: 30000          # approximate, used as a sanity band
```

Known members of the set, useful as a cross-check while extracting the full list: the canonical plays and
poems, plus the apocryphal texts that the prior study flagged, among them *A Yorkshire Tragedy*,
*Arden of Feversham*, *Locrine*, *Mucedorus*, *The London Prodigal* and *The Puritan Widow*.
Length range runs from roughly 2,100 words (*A Lover's Complaint*) to roughly 30,000 words (*Hamlet*).

**Legal note:** all texts are public domain. Redistributing the plain-text corpus inside the repository
is acceptable. Keep the Project Gutenberg licence header in `data/corpus/LICENSE_SOURCES.md` and record
provenance per text in the manifest.

## 3. Prior published findings (comparison target, not ground truth)

The prior study's CNN variant flagged 15 of the 49 as suspicious. Record that list in
`data/prior_findings.yaml` and use it **only** for the agreement report. It must never influence the
threshold, the profile, or any decision inside the pipeline.

The success metric that does carry weight is agreement with **scholarly consensus** on the firmest
co-authorship cases: Henry VIII with Fletcher; Henry VI Parts I, II and III with Marlowe; Timon of
Athens with Middleton. Record these in `data/consensus_cases.yaml` with the citation for each.

## 4. Normalization

Applied once at ingest, and the normalized text is what is stored in `data/corpus/`. Chunking, rewriting
and distance all operate on normalized text, so the pipeline is deterministic from that point on.

1. Decode as UTF-8. Reject any file that fails to decode.
2. **Strip Project Gutenberg boilerplate.** Cut everything before the `*** START OF THE PROJECT
   GUTENBERG EBOOK ...***` marker and everything after the corresponding `*** END OF ...***` marker.
   If a marker is missing, fail loudly rather than guessing. Handle the older `***START OF THE PROJECT
   GUTENBERG EBOOK` spelling variants.
3. **Strip editorial apparatus** that is not the author's text: transcriber notes, tables of contents,
   and the dramatis personae block. Keep speaker names or drop them, but do it **identically for every
   text** and record the choice in the manifest. Recommended: keep the text as printed, including speaker
   prefixes, because they are stylistically inert for function-word analysis and removing them risks
   inconsistent heuristics across texts.
4. Unicode normalize to NFKC. Map typographic quotes to ASCII: `‘ ’ → '`, `“ ” → "`. Map en and em
   dashes to a single hyphen surrounded by spaces. Preserve everything else.
5. Collapse runs of three or more blank lines to two. Strip trailing whitespace per line.
   Do **not** collapse intra-line spacing beyond a single space, and do not re-wrap lines.
6. Do **not** lowercase, do **not** remove punctuation, and do **not** modernize spelling.
   Original orthography is part of the signal, and the LLM is asked to rewrite real text.

Lowercasing and punctuation stripping happen only inside the distance tokenizer (section 5), never in
the stored corpus.

**A word**, for chunking and for length statistics, is a maximal run of non-whitespace characters in the
normalized text.

## 5. Function words and the distance tokenizer

### 5.1 The list

`data/function_words/en_core_v1.txt`, one lowercase entry per line, `#` comments allowed, sorted.
The list mixes modern and Early Modern English forms so that no prior knowledge of the target author's
usage is baked into the metric. The file is versioned: changing it means a new file
(`en_core_v2.txt`), never an edit in place, because it invalidates every previously computed delta.
The manifest records the filename, its sha256, and the exact entry count.

`tests/unit/test_function_words.py` asserts: all lowercase, no duplicates, no whitespace inside an entry,
and a total between 110 and 130 entries, matching the book's "approximately 120".

**v1 composition:**

```
# articles
a an the

# pronouns, modern
i me my myself you your yours yourself he him his himself
she her herself it its we us our they them their

# pronouns, Early Modern
thou thee thy thine thyself ye

# relative and demonstrative
who whom whose which what that this these those

# be, have, do
am is are was were be been have has had do does did

# modals
will would shall should can could may might must

# verb forms, Early Modern
art wert hast hath dost doth didst shalt wilt canst wouldst shouldst couldst

# prepositions
of in to for with on at by from into upon unto about over under above
through between against within without until

# conjunctions
and but or nor if because as than though although while since

# negation and adverbials
not no never ever very too only then

# quantifiers and determiners
all any some both each such more most other
```

### 5.2 Extraction, `FW(x)`

Exactly these steps, in this order:

1. NFKC normalize; map `’` to `'`.
2. Lowercase (`str.casefold()`).
3. Split on whitespace.
4. For each token, strip leading and trailing characters in
   `.,;:!?"()[]{}<>*_—–-` . **Do not strip apostrophes**, because Early Modern elisions
   (`'tis`, `th'`, `ne'er`) are meaningful tokens.
5. Discard empty tokens.
6. Keep only tokens that are members of the function-word set, **preserving their original order**.

The result is an ordered sequence, not a set and not a bag. Order matters: it is what makes FWED
sensitive to syntactic style rather than to vocabulary frequency alone.

### 5.3 Worked example (a golden test)

```
original: "Do you know what he does when the night comes?"
rewrite : "Dost thou know what he doth when the night comes?"

FW(original) = [do,   you,  what, he, does, the]            |FW| = 6
FW(rewrite)  = [dost, thou, what, he, doth, the]            |FW| = 6

edits: do -> dost, you -> thou, does -> doth        lev = 3 substitutions
delta = 3 / max(6, 6) = 3 / 6 = 0.5
```

Content words (`know`, `night`, `comes`) are not in the list and are correctly dropped.

`when` is dropped too, and that is not an oversight in the example: the v1 list in section 5.1 has no
wh-adverbs. Whether it should is open — see `docs/OPEN_QUESTIONS.md` Q10 — but until that is settled
the list above is the instrument, and the example must show what the instrument actually does.

`tests/unit/test_fwed.py` must contain at least one hand-verified case with this arithmetic written out
in the docstring. Re-derive the value yourself when writing the test rather than copying it from a
document: a wrong golden value is worse than none, because it makes a broken metric look verified.

### 5.4 Sequence Levenshtein

`python-Levenshtein` operates on strings, not on token sequences. Map each distinct function word to a
unique code point in the Unicode private use area (`U+E000` upward, assigned by sorted list order),
encode both sequences, and take the string distance. The mapping is injective, so the result is exactly
the sequence-level edit distance. A pure-Python dynamic-programming implementation lives in the tests
and is cross-checked against the fast path on randomly generated sequences with `hypothesis`.

## 6. Manifest

`data/manifest.json`, generated by `python -m mmlsa corpus manifest` and verified by
`python -m mmlsa corpus verify`.

```json
{
  "generated_utc": "2026-08-04T10:00:00Z",
  "normalization_version": 1,
  "speaker_prefixes": "kept",
  "function_words": { "file": "en_core_v1.txt", "sha256": "…", "count": 124 },
  "sets": {
    "corpus":  [ { "id": "hamlet", "title": "Hamlet", "sha256": "…",
                   "n_words": 30217, "n_chars": 172004, "source_url": "…",
                   "gutenberg_id": 1524 } ],
    "noise_pool": [ … ], "heldout": [ … ], "mixture_sources": [ … ]
  },
  "heldout_frozen_utc": "2026-08-20T00:00:00Z"
}
```

`corpus verify` checks: every file decodes, every checksum matches, the corpus has the expected count,
no Gutenberg marker survives in any normalized file, no text id appears in two sets, and every word
count falls inside its declared sanity band.

## 7. Token budgeting

The profile step needs a token estimate per text to pack calls. Use the provider's own counting endpoint
where available; otherwise `n_tokens ≈ n_words * 1.35` for Early Modern English prose, which is
deliberately conservative. Cache the counts in the manifest so packing is stable across runs.

Corpus-level expectation: roughly 0.9 to 1.0 million words, so roughly 1.2 to 1.35 million tokens.
This exceeds a one-million-token context window, which is why multi-call packing plus a merge call is
the real path and not a rare fallback. See `docs/SPEC.md` section 3, Step 1.
