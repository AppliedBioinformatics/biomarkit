# Biomarkit
## Overview
Biomarkit is a Python package for automated publisher-agnostic corpus download and structured Markdown file conversion 
for full-text scientific publications.




---


## How it works.
### `extract_text()`
Attempt to download full-text PDFs or XML files for all publications listed in a Scopus query CSV file by DOI. 
Each DOI is routed through a two-stage API download process that checks fully-open access availability of the DOI from
sites such as Unpaywall and bioRxiv, before attempting download from the DOI's respective publisher directly (Springer/
Wiley etc.). Outputs a summary report to inform user of corpus download success rate, download success per publisher, and 
other useful metrics.

See [docs/devs/text_extraction.md](docs/devs/text_extraction.md) for the full documentation.

---

### `text_transformation()`
Converts downloaded PDFs and XML files into a single, structured JSON format. XMLs are parsed directly, and PDFs are
converted locally via MinerU (GPU can be used here for speedup). Outputs a HTML report to inform user of conversion
success rate and other metrics.

See [docs/devs/text_transformation.md](docs/devs/text_transformation.md) for full documentation.

---

### `standardise_text()`
Converts JSON-structured text into a standardised Markdown format. A single Markdown file is generated for each
document. Supports parameters for toggling inclusion of manuscript sections: figures, tables, references, and Latex 
equations.

The "force_imrad_structure" parameter will force each output Markdown file to contain marked sections for "Introduction"
"Methods", "Results" and "Discussion" (can be omitted). Outputs a HTML report to inform user of useful output metrics 
for the corpus.

---

## Example:
```python
# Complete a full download and generate Markdown files for each DOI in a given Scopus query
from main import extract_text, transform_text, standardise_text

# active corpus defined in config.py
publications = extract_text(check_opensource=True, scopus_report=True)
publications = transform_text(publications)
standardise_text(publications, keep_figures=False, keep_tables=True, keep_latex=True, force_imrad_structure=True)
```

`Publication` Python objects are returned from each step and are useful for integrating the package within larger 
Python workflows:

```Python
from main import extract_text
publications = extract_text(check_opensource=True)

# Store metadata for all DOIs in the active corpus: 
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
## Corpus Layout

All inputs and outputs live under `corpora/<corpus_name>/`. The active corpus can be changed by setting
`CORPUS_NAME` in `config.py`. Each corpus folder has the following structure:

```
corpora/
└── <corpus_name>/
    ├── scopus.csv       # Scopus query export (input — you need to place this here)
    ├── manuscripts/     # Downloaded full-text PDFs/XMLs  output of `extract_text()`
    ├── markdowns/       # MinerU output files and JSON structures - output of `transform_text()`
    ├── results/         # Final standardised Markdown files - output of `standardised_text()`
    ├── reports/         # All HTML output reports.
    ├── logs/            # Run logs
    └── sqlite.db        # SQLite cache for this corpus
```
Everything except `scopus.csv` is created automatically on the first run when defining a new active corpus..

---

## Configuration

Key settings are in `config.py`:

| Setting | Description |
|---|---|
| `CORPUS_NAME` | Name of the active corpus folder under `corpora/` |
| `MAX_THREADS` | Max parallel threads for API downloads |
| `LLM_BASE_URL` | OpenAI-compatible endpoint for the fallback section classifier (defaults to local [Ollama](https://ollama.com)) |
| `LLM_MODEL_NAME` | Model used by the fallback classifier (default `llama3.2:b`) |

Secrets (API keys) are read from `secrets.env` — see `secrets.env.example`.

---

## Dependencies
- Python 3.12–3.13:
- Optional: A CUDA-capable GPU (big speedup for PDF conversion via MinerU) + `torch` (CUDA 12.8)
- Optional: [Ollama](https://ollama.com/download) running `llama3.2:8b` (~8 GB), used as an LLM fallback to classify 
ambiguous section headings. Without it, the pipeline runs, but accuracy in removing paper boilerplate is decreased.

Core dependencies: `pandas`, `pydantic`, `requests`, `playwright`, `plotly`, `openai`, `wiley-tdm`, `mineru[pipeline]`, `torch`

# Installation
Install with [uv](https://github.com/astral-sh/uv):

```bash
uv pip install biomarkit
```