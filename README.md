# Biomarkit
A Python package for automated publisher-agnostic corpus download and structured Markdown file conversion 
for full-text scientific publications.

---

## Overview
### Full-text manuscript download with `download_corpus()`.
Downloads full-text PDFs or XML files for all publications listed in a Scopus query CSV file by DOI.
Each DOI is routed through a two-stage process: open-access routes (arXiv, bioRxiv, Unpaywall) are
tried first, then publisher APIs (Elsevier, Wiley, Springer, MDPI, Frontiers, etc.) handle the remainder.
Set `generate_report=True` to output an HTML summary of download success rates and per-publisher metrics.

### Derive JSON structures from PDF and XML files with `text_transformation()`.
Converts downloaded PDFs and XML files into a single, structured JSON format. XMLs are parsed directly, and PDFs are
converted locally via MinerU (GPU can be used here for speedup). Outputs a HTML report to inform user of conversion
success rate and other metrics.

Also outputs raw-markdown text files and figure.png file outputs from [MinerU](https://github.com/opendatalab/mineru).


### Convert all manuscripts to a standardised markdown format with `standardise_text()`.
Converts JSON-structured text into a standardised Markdown format. A single Markdown file is generated for each
document. Supports parameters for toggling inclusion of manuscript sections: figures, tables, references, and Latex 
equations.

The "force_imrad_structure" parameter will force each output Markdown file to contain marked sections for "Introduction"
"Methods", "Results" and "Discussion" (can be omitted). Outputs a HTML report to inform user of useful output metrics 
for the corpus.


### The corpus folder structure

All inputs and outputs for a scopus query live under `corpora/<corpus_name>/`. The active corpus is selected by setting
`CORPUS_NAME` in `secrets.env`. Each corpus folder has the following structure:

```
corpora/
└── <corpus_name>/
    ├── scopus.csv       # Scopus query export (input — you need to place this here)
    ├── manuscripts/     # Downloaded full-text PDFs/XMLs  output of `extract_text()`
    ├── intermediates/   # MinerU output files and JSON structures - output of `transform_text()`
    ├── results/         # Final standardised Markdown files - output of `standardised_text()`
    ├── reports/         # All HTML output reports.
    ├── logs/            # Run logs
    └── sqlite.db        # SQLite cache for this corpus
```
Everything except `scopus.csv` is created automatically on the first run when defining a new active corpus. You can 
create a new corpus by running the function `create_corpus(name="my_corpus", scopus_file="path/to/scopus.csv")`.

---

## Example:
### Complete a full download and generate markdown files for each DOI in a given Scopus query:

```python
from main import download_corpus, transform_text, standardise_text, build_new_corpus

# Make a new corpus and set it as active (writes CORPUS_NAME to secrets.env)
build_new_corpus(name="my_corpus", scopus_file="path/to/scopus.csv", set_active=True)

# Attempt download for all DOIs:
publications = download_corpus(check_opensource=True, generate_report=True)

# Run OCR and XML parser to generate JSON document structures:
publications = transform_text(publications)

# Build final markdown files:
standardise_text(publications, keep_figures=False, keep_tables=True, keep_latex=True, force_imrad_structure=True)
```

### Publications as Python objects:
`Publication` Python objects are returned at each step and are useful for integrating the package within larger 
Python workflows. For example, storing each publication as a Python object makes it easy to query metadata and filepaths:

```Python
from main import download_corpus

publications = download_corpus(check_opensource=True)

# Query metadata for all DOIs in the active corpus: 
for pub in publications:
    print(pub.doi,
          pub.title,
          pub.abstract,
          pub.publisher,
          pub.document_type,
          pub.publication_filepath,
          pub.final_md_filepath
          )
```

---
## Configuration

All user-facing settings live in `secrets.env` (copy from `secrets.env.example`):

| Setting | Description |
|---|---|
| `CORPUS_NAME` | Name of the active corpus folder under `corpora/` |
| `USER_EMAIL` | Your email address (required by some publisher APIs) |
| `WILEY_TDM_TOKEN` | Wiley TDM API token (optional) |
| `SPRINGER_API_KEY` | Springer API key (optional) |
| `ELSEVIER_API_KEY` | Elsevier API key (optional) |
| `LLM_BASE_URL` | OpenAI-compatible endpoint for the fallback section classifier (defaults to local [Ollama](https://ollama.com)) |
| `LLM_MODEL_NAME` | Model used by the fallback classifier (default `gemma3:12b`) |

---

## Dependencies
- Python 3.12–3.13:
- Optional: A CUDA-capable GPU (big speedup for PDF conversion via MinerU) + `torch` (CUDA 12.8)
- Optional: [Ollama](https://ollama.com/download) running `gemma3:12b` (~8 GB), used as an LLM fallback to classify 
ambiguous section headings. Without it, the pipeline runs, but accuracy in removing paper boilerplate is decreased.

Core dependencies: `pandas`, `pydantic`, `requests`, `playwright`, `plotly`, `openai`, `wiley-tdm`, `mineru[pipeline]`, `torch`

# Installation
Install with [uv](https://github.com/astral-sh/uv):

```bash
uv pip install biomarkit
```