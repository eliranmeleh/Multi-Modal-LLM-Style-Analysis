# Appendix 1 — Reproducibility Guide

*Capstone Project Phase B, project 26-2-R-6: Multi-Modal LLM Style Analysis.*

This guide is for anyone who wants to reproduce the results reported in the project book: a
supervisor, the peer examiner, or a future researcher. It gives the exact commands, the parameters
they use and the outputs to expect, for the runs that produced the reported numbers.

There are two ways to reproduce the results:

| Path | What it does | Needs | Time | Cost |
|---|---|---|---|---|
| **A. Replay** (recommended) | Re-runs every step of the method from the model answers recorded in the original run, and checks that the scores come out byte for byte the same | Python, the repository, the release archive | minutes | none |
| **B. Live re-run** | Sends every request to the model again | Python, the repository, an API key | about 1 to 2 hours for the full corpus | a few dollars |

Path A reproduces the reported numbers exactly. Path B reproduces the method: a language model at
temperature 0 is close to deterministic but not exactly so, so a live re-run gives scores close to,
not identical with, the reported ones. Section 6 explains why that is expected.

**Placeholders.** `<RUN_ID>` stands for the run of record, whose id is given in the project book
and in `docs/RESULTS.md`; `<RELEASE_URL>` for the GitHub release that holds its archive. Every other
value in this guide is exact.

---

## 1. Requirements

- **Python 3.11, 3.12 or 3.13.** The reported runs were made on 3.11.
- **Git.**
- About 1 GB of free disk space for the environment and a full run directory.
- Windows, macOS or Linux. Or no installation at all: Google Colab (section 7).
- For path B only, an API key for the model provider (section 5).

No GPU is needed: the model runs at the provider, and everything else is ordinary arithmetic.

## 2. Install

```bash
git clone https://github.com/eliranmeleh/Multi-Modal-LLM-Style-Analysis.git
cd Multi-Modal-LLM-Style-Analysis

python -m venv .venv
# Windows:        .venv\Scripts\activate
# macOS / Linux:  source .venv/bin/activate

pip install -e ".[dev]"
```

To reproduce with the exact source code of the reported run, check out the commit recorded in that
run's `manifest.json` (field `git_commit`) before installing: `git checkout <commit>`.

**Check the installation.** Both commands must succeed:

```bash
python -m mmlsa --help
python -m mmlsa corpus verify
```

`corpus verify` checks the 49 texts under `data/corpus/` against the checksums in
`data/manifest.json` and must end with every check passing. The texts are part of the repository,
so nothing is downloaded. (`python -m mmlsa corpus fetch` rebuilds them from Project Gutenberg, but
reproduction does not need it.)

**Optional: run the test suite.** It makes no network call and needs no key:

```bash
MMLSA_ALLOW_LIVE=0 pytest -q        # Windows PowerShell: $env:MMLSA_ALLOW_LIVE="0"; pytest -q
```

## 3. A first run in seconds, with no key

Before the real data, run the whole method once on a three-text example with a built-in offline
model. It exercises every step and every output file:

```bash
python -m mmlsa run --config configs/mini.yaml --provider fake --run-id demo
python -m mmlsa report --run-id demo --config configs/mini.yaml
```

Expected: the first command ends with `tau 0.0517 (otsu_exact)` and `suspicious 1 of 3`, naming
`mini_beta`, and creates `runs/demo/`; the second writes `reports/demo/report.md`. These numbers are
fixed, so a different value means the installation differs from the one the project was tested on.

## 4. Path A: replay the reported run

### 4.1 Get the release

From `<RELEASE_URL>`, download `<RUN_ID>.tar.gz` and `<RUN_ID>.tar.gz.sha256` into the repository
root, then check the archive and unpack it:

```bash
sha256sum -c <RUN_ID>.tar.gz.sha256         # must print: <RUN_ID>.tar.gz: OK
tar -xzf <RUN_ID>.tar.gz                    # creates runs/<RUN_ID>/ and cache/
```

(Windows PowerShell: `Get-FileHash <RUN_ID>.tar.gz -Algorithm SHA256` and compare with the file;
`tar` is built into Windows 10 and later.)

The archive holds the finished run directory and exactly the recorded model answers that run used,
one file per request, named by a SHA-256 hash of the request.

### 4.2 Reproduce

```bash
python -m mmlsa reproduce --run-id <RUN_ID>
```

This reads the run's own configuration from `runs/<RUN_ID>/config.snapshot.yaml`, re-runs all six
steps of the method in **replay mode** into a temporary folder, and compares the result with the
released run. Replay mode never contacts a model: every request is answered from `cache/`, and an
answer that is missing is an error, not a request. No API key is needed.

**Expected output** (the replay folder differs per machine):

```
replayed run    <temporary folder>/<RUN_ID>
  scores.csv       identical
  threshold.json   identical
record          <temporary folder>/<RUN_ID>.reproduction.json
REPRODUCED      byte for byte
```

`scores.csv` holds every creation's score and label; `threshold.json` holds the threshold `tau` and
its diagnostics. Byte-for-byte equality of both means every number in the book's results tables is
reproduced. The command exits with code 0 when they match and 1 when they do not.

The same replay without the comparison, writing a normal run directory, is:

```bash
python -m mmlsa run --config configs/full.yaml --mode replay
```

### 4.3 Regenerate the report

```bash
python -m mmlsa report --run-id <RUN_ID> --config configs/full.yaml
```

This writes `reports/<RUN_ID>/`: `report.md` with the tables of the book's results chapter, the
same tables as CSV, and the figures. It sends no request. Section 8 maps each part to the book.

## 5. Path B: re-run live

### 5.1 The key

Create a file `.env` in the repository root (copy `.env.example`) containing

```
GEMINI_API_KEY=<your key>
```

and install the provider's client: `pip install -e ".[gemini]"`. The key is read from the
environment only. It is never written to any file the program creates.

### 5.2 The parameters of the run of record

All parameters live in one configuration file, `configs/full.yaml`, which inherits every value it
does not set from `configs/default.yaml`. The values that define the reported run:

| Parameter | Key | Value |
|---|---|---|
| Corpus | `corpus.include_ids` | all 49 creations in `data/corpus/` |
| Chunk length `P` | `chunking.P` | 400 words |
| Independent runs `M` | `run.M` | 3 |
| Noise injection | `noise.enabled` | on: run 1 plain, runs 2 and 3 each add one foreign text from `data/noise_pool/` |
| Model | `llm.provider`, `llm.model_id` | as recorded in the run's `manifest.json` (`provider`, `model_id`) |
| Temperature | `llm.temperature` | 0.0 |
| Distance | `distance.metric` | `fwed`, function words from `data/function_words/en_core_v1.txt` |
| Threshold | `classify.method` | `otsu_exact`, borderline band 0.01 |
| Seed | `run.seed` | 20260731 |

The authoritative record is the run's own `config.snapshot.yaml`, which holds every resolved value,
defaults included. If it differs from this table, the snapshot is right.

### 5.3 Run

Always look at the plan first. `--dry-run` prints the number of calls and the estimated tokens and
sends nothing:

```bash
python -m mmlsa run --config configs/full.yaml --set llm.model_id=<model_id> --dry-run
python -m mmlsa run --config configs/full.yaml --set llm.model_id=<model_id>
```

On a paid key, add `--set llm.concurrency=8 --set llm.requests_per_minute=240`; the defaults are
sized for a free tier and are much slower. The command prints the run id and the threshold when it
finishes, and writes `runs/<new run id>/` with the files in section 8.

An interrupted run is resumed with the same command plus `--run-id <run id>`. Requests already
answered are read from `cache/` and are not paid for again.

## 6. What "reproduced" means here

- **Replay (path A) is exact.** The deterministic steps (chunking, distance, averaging, threshold)
  are pure functions of the recorded model answers, so the same answers give the same bytes.
  This is checked automatically by `tests/integration/test_report_release.py`, which releases a run,
  unpacks it into an empty folder and reproduces it from the archive alone.
- **A live re-run (path B) is close, not identical.** Even at temperature 0, a hosted model may
  return a slightly different text for the same request, and providers update models behind a
  name. Expect individual scores to move a little. What should hold is what the book claims: the
  same creations on each side of the threshold, apart from those it reports as borderline. The
  stability of labels across independent runs is measured, and reported, by the Stage 2 experiment.
- **Caching makes repeated runs free.** Every answer is stored under a hash of its request, so
  running the same command again costs nothing and returns the same result.

## 7. In Google Colab, with nothing installed

Open `notebooks/Multi-Modal-LLM-Style-Analysis.ipynb` from the repository's README ("Open in
Colab") and choose Runtime → Run all. It clones the repository, installs it, runs section 3's
offline example, and, with a key stored in Colab Secrets as `GEMINI_API_KEY`, makes a small live
run and shows each step's output. Without a key the live part is skipped.

## 8. Outputs, and where they appear in the book

A run directory `runs/<RUN_ID>/`:

| File | Contents |
|---|---|
| `manifest.json` | run id, code commit, model and model version, seed, start and end time, call and token counts |
| `config.snapshot.yaml` | every parameter of the run, resolved |
| `profiles/run_<i>_merged.json` | the style profile extracted in run `i` |
| `chunks/<creation>.jsonl` | the 400-word chunks of each creation |
| `rewrites/run_<i>/<creation>.jsonl` | each chunk's rewrite in run `i` |
| `deltas/run_<i>.csv` | the distance of every chunk in run `i` |
| `scores.csv` | per creation: the score of each run, their mean and standard deviation, the label, borderline flag |
| `threshold.json` | `tau`, the method, and the bimodality diagnostics |
| `noise_diagnostics.csv` | the score of each injected foreign text, which should lie above `tau` |
| `figures/` | `sorted_scatter.png`, `histogram.png`, `run_variance.png` |
| `calls.jsonl` | every model request and response, with model version, tokens, latency and time |

The report `reports/<RUN_ID>/report.md` and the experiments:

| Book result | Command | Output |
|---|---|---|
| Scores, threshold, suspicious set | `run --config configs/full.yaml` | `scores.csv`, `threshold.json`, `figures/` |
| Success metric 1: stable labels | `report --run-id <RUN_ID>`; across `P`: `experiment sensitivity --config configs/sensitivity.yaml --yes` | report section "Success metric 1"; the sweep's `summary.md` |
| Success metric 2: the profile matters | `experiment control --config configs/control.yaml --yes` | `control.json`, `summary.md` |
| Success metric 3: consensus cases | `report --run-id <RUN_ID>` | report section "Success metric 3" |
| Agreement with the prior study | `report --run-id <RUN_ID>` | report section and `prior_agreement.csv` |
| Calibration, mixture, held-out checks | `experiment calibration\|mixture\|heldout --baseline <RUN_ID> --yes` | `<check>.json`, `summary.md` |
| Noise robustness | `experiment noise --with-noise <RUN_ID> --without-noise <RUN_ID_2>` | `noise.json`, `summary.md` |

Every experiment command prints its plan (calls and tokens) and stops unless `--yes` is given.
Each experiment writes its own run directory under `runs/`, and its release replays the same way as
section 4: `python -m mmlsa reproduce` for the main run, and the recorded check bundles under
`tests/fixtures/recorded_runs/` with `pytest tests/validation -q`.
