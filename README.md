# Multi-Modal LLM Style Analysis

**Detecting Misattributed Creations in the Shakespeare Corpus through LLM-Based Style Normalization**

Final Project — Phase A (course 61998), Software Engineering Department, Braude College of Engineering.
Project code: **26-2-R-6**

**Students:** Eliran Melihov · Miron Hanukaiev
**Advisors:** Dr. Renata Avros · Prof. Zeev Volkovich

## Overview

The project proposes an unsupervised, zero-shot complement to classifier-based computational stylometry. A large language model extracts a generic style profile from the 49-creation Shakespeare corpus and rewrites each creation's chunks to match that profile while preserving content. The Function-Word Edit Distance between each chunk and its rewrite (one of several distance measures to be compared in Phase B) measures how much stylistic change was required: authentic chunks need little change, chunks by other authors change substantially. A parameter-free threshold on the per-creation scores, averaged over M independent runs, separates authentic from suspicious creations.

The method continues the line of research of Volkovich & Avros (2025), *Comprehension of the Shakespeare authorship question through deep impostors approach*, Digital Scholarship in the Humanities, 40(1), 308–328. https://doi.org/10.1093/llc/fqaf009

## Repository contents

| Path | Description |
|---|---|
| `book/Project_Book_Phase_A.docx` / `.pdf` | The Phase A project book (submission document, 20 pages) |
| `presentation/Project_Phase_A_Presentation.pptx` / `.pdf` | The Phase A final presentation (15 slides) |

Phase B will add the pipeline implementation, configuration, experiment logs, and result files to this repository.
