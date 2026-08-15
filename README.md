# Multi-Modal LLM Style Analysis

Detecting misattributed creations in a literary corpus through LLM-based style normalization.

Braude College of Engineering, Software Engineering Department. Capstone Project, code 26-2-R-6.
Eliran Melihov and Miron Hanukaiev. Advisors: Dr. Renata Avros and Prof. Zeev Volkovich.

---

## Idea

Ask a large language model to rewrite a passage into the dominant style of a corpus. A passage already
written in that style barely changes. A passage by a different hand must change substantially. The size
of the required change is a measurable stylistic distance, and it separates the two cases.

The pipeline is unsupervised and zero-shot. It needs no corpus of comparison authors, trains no
classifier, and produces a per-creation score that reads in plain stylistic terms: the share of function
words the model had to alter.

The running corpus is the 49 creations attributed to William Shakespeare, chosen so that results can be
compared against published computational stylometry on the same texts. Nothing in the method is specific
to that corpus. No author name is hard-coded anywhere in the source.

## Method

Six steps, executed as `M` independent runs whose per-creation scores are averaged.

| Step | What happens |
|------|--------------|
| 1 | A style profile is extracted from the full corpus by the LLM. The prompt names no author. |
| 2 | Every creation is split into consecutive same-size chunks of `P` words. Full coverage, no sampling. |
| 3 | Each chunk is rewritten under that run's profile, preserving content and changing only style. |
| 4 | A style distance is computed between each chunk and its rewrite. The metric developed with the method is the Function-Word Edit Distance. |
| 5 | Chunk distances are averaged into a per-creation score, then averaged across the `M` runs. The spread across runs is a confidence diagnostic. |
| 6 | A parameter-free one-dimensional threshold splits the scores into authentic and suspicious. |

The Function-Word Edit Distance between a chunk `c` and its rewrite `r`:

```
delta(c, r) = lev( FW(c), FW(r) ) / max( |FW(c)|, |FW(r)| )
```

where `FW(x)` is the ordered sequence of function words in `x`, drawn from a fixed list of approximately
120 modern and Early Modern English forms, and `lev` is the Levenshtein distance between the two
sequences. The value lies in `[0, 1]` and reads directly as the proportion of function-word usage that
had to change.

The distance metric and the threshold method are both treated as one option among several, compared
empirically rather than assumed.

## Install

Requires Python 3.11.

```bash
git clone https://github.com/eliranmeleh/Multi-Modal-LLM-Style-Analysis.git
cd Multi-Modal-LLM-Style-Analysis

uv venv --python 3.11 .venv                  # or use any Python 3.11 interpreter
uv pip install --python .venv -e ".[dev]"    # or: pip install -e ".[dev]"

cp .env.example .env      # then add an API key for the chosen provider
```

## Use

```bash
python -m mmlsa corpus fetch                             # download and normalize the corpus
python -m mmlsa corpus verify                            # checksums and integrity

python -m mmlsa run --config configs/poc.yaml --dry-run  # call count and token estimate, no requests
python -m mmlsa run --config configs/poc.yaml            # proof-of-concept subset
python -m mmlsa run --config configs/full.yaml           # full corpus

python -m mmlsa report --run-id <run_id>
```

Run without an API key at all, for development and testing:

```bash
python -m mmlsa run --config configs/mini.yaml --provider fake
```

## Reproducing a published run

Every LLM call is content-addressed and logged. A recorded run can be replayed exactly, offline and with
no API calls:

```bash
python -m mmlsa run --config configs/full.yaml --mode replay
```

Each run writes an immutable directory under `runs/` containing the resolved configuration, the extracted
profiles, per-chunk distances, per-creation scores, the threshold, the figures, and a complete ledger of
every call with its prompt, response, model version and timestamp.

## Results

Populated at the end of Phase B: the sorted scatter with the threshold marked, the suspicious set with
continuous scores and per-creation confidence, and an agreement table against published findings on the
same corpus.

## Repository layout

```
src/mmlsa/       pipeline, distance metrics, LLM providers, reporting
configs/         run configurations
data/            corpora, function-word list, manifests
docs/            specification, architecture, data, prompts, plan, experiments, testing, decisions
tests/           unit, contract, integration, data-integrity and validation suites
runs/            run artifacts
book/            the Phase A project book (submission document)
presentation/    the Phase A final presentation
```

Start with `docs/SPEC.md` for the method and `docs/ARCHITECTURE.md` for the code.
`docs/STATUS.md` says where the implementation currently stands.

## Related work

Volkovich, Z., and Avros, R. (2025). Comprehension of the Shakespeare authorship question through deep
impostors approach. *Digital Scholarship in the Humanities*, 40(1), 308–328.
https://doi.org/10.1093/llc/fqaf009

This project continues that line of research on the same corpus, exploring an unsupervised, LLM-based
alternative to the trained-classifier approach.

## Licence

MIT. Corpus texts are public domain, sourced from Project Gutenberg; see
`data/corpus/LICENSE_SOURCES.md`.
