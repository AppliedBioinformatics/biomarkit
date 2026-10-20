# Biomarkit

A Python package for automated publisher-agnostic corpus download and structured Markdown file conversion 
for full-text scientific publications.

---

## Overview
### Full-text manuscript download from major publishers with `download_corpus()`.
Attempt download of full-text PDFs and XML files for all publications listed in a Scopus query CSV file by DOI.
Download is attempted first via open-access routes including arXiv, bioRxiv and Unpaywall. On failure, download is 
attempted using specific publisher APIs including Elsevier, Wiley, Springer, MDPI, Frontiers.

**API keys are required for publishers that do not support fully automated text-mining**

### Derive JSON manuscript structures from PDF and XML files with `transform_text()`.
Converts downloaded PDFs and XML files into a single, structured JSON format. XMLs are parsed directly, and PDFs are
converted locally with [MinerU](https://github.com/opendatalab/mineru) 4. Choose a MinerU quality tier with
`mineru_tier`: `"basic"` (small models only, fine on CPU), `"standard"` (default; adds the MinerU vision-language model
for complex layouts, best on a GPU) or `"advanced"` (more VLM compute for hard documents). Captures other outputs
including raw texts and figures.


### Convert all manuscripts to a customisable Markdown format with `standardise_text()`.
Converts JSON-structured text into a standardised Markdown format. A single Markdown file is generated for each
document. Supports parameters for toggling inclusion of manuscript sections: figures, tables, references, and Latex 
equations.

The "force_imrad_structure" parameter will force each output Markdown file to contain marked sections for "Introduction"
"Methods", "Results" and "Discussion" (can be omitted).

---

## Example:
### Complete a full download and generate markdown files for each DOI in a given Scopus query:

```python
import biomarkit

# Select the corpus for this session (asks to build it from the Scopus export if it doesn't exist yet):
biomarkit.load_corpus("my_corpus", scopus_file="path/to/scopus.csv")

# Attempt download for all DOIs:
publications = biomarkit.download_corpus(check_opensource=True, generate_report=True)

# Run MinerU and the XML parser to generate JSON document structures:
publications = biomarkit.transform_text(publications, mineru_tier="standard")

# Build final markdown files:
biomarkit.standardise_text(publications, keep_figures=False, keep_tables=True, keep_latex=True, force_imrad_structure=True)
```

### Publications as Python objects:
`Publication` Python objects are returned at each step and are useful for integrating the package within larger 
Python workflows. For example, storing each publication as a Python object makes it easy to query metadata and filepaths:

```python
import biomarkit

biomarkit.load_corpus("my_corpus")
publications = biomarkit.download_corpus(check_opensource=True)

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

`load_corpus()` itself returns the `Publication` objects for every manuscript already downloaded, so you can get them
back without triggering a new download run.

---
## Configuration

### Workspace directory

By default, biomarkit creates a `corpora/` folder in your **current working directory**. To use a different location, set the `BIOMARKIT_DIR` environment variable before running:

```bash
# Linux/macOS
export BIOMARKIT_DIR=/path/to/my/workspace

# Windows (PowerShell)
$env:BIOMARKIT_DIR = "C:\path\to\my\workspace"
```

Biomarkit also looks for `secrets.env` inside this directory.

### API keys and settings

All user-facing settings live in `secrets.env` (copy from [`secrets.env.example`](secrets.env.example) and place it in your workspace directory):

| Setting | Description |
|---|---|
| `USER_EMAIL` | Your email address (required by some publisher APIs) |
| `WILEY_TDM_TOKEN` | Wiley TDM API token (optional) |
| `SPRINGER_API_KEY` | Springer API key (optional) |
| `ELSEVIER_API_KEY` | Elsevier API key (optional) |
| `LLM_BASE_URL` | OpenAI-compatible endpoint for the fallback section classifier (defaults to local [Ollama](https://ollama.com)) |
| `LLM_MODEL_NAME` | Model used by the fallback classifier (default `gemma3:12b`) |
| `MINERU_VLM_SERVER_URL` | Optional remote server for MinerU's VLM (e.g. vLLM serving `opendatalab/MinerU2.5-Pro-2605-1.2B`); leave blank to run the VLM locally |
| `MINERU_VLM_API_KEY` | API key for that server, if it requires one |

### The corpus folder structure

All inputs and outputs for a Scopus query live in one corpus folder: `corpora/<corpus_name>/` inside your workspace directory, or any folder path you pass to `load_corpus()`. The active corpus is selected in your script by calling `biomarkit.load_corpus(...)`. Each corpus folder has the following structure:

```
corpora/
└── <corpus_name>/
    ├── scopus.csv       # Scopus query export (input)
    ├── manuscripts/     # Downloaded full-text PDFs/XMLs — output of `download_corpus()`
    ├── intermediates/   # MinerU output files and JSON structures — output of `transform_text()`
    ├── results/         # Final standardised Markdown files — output of `standardise_text()`
    ├── reports/         # All HTML output reports
    ├── logs/            # Run logs
    └── sqlite.db        # SQLite cache for this corpus
```
Everything is created automatically. Create a new corpus with `load_corpus("my_corpus", scopus_file="path/to/scopus.csv")`; it asks for confirmation before building, or pass `build=True` to skip the prompt (e.g. in batch jobs).

---

## Dependencies
- Python 3.12–3.13:
- Optional: A CUDA-capable GPU (big speedup for PDF conversion via MinerU) + `torch` (CUDA 12.8)
- Optional: [Ollama](https://ollama.com/download) running `gemma3:12b` (~8 GB), used as an LLM fallback to classify 
ambiguous section headings. Without it, the pipeline runs, but accuracy in removing paper boilerplate is decreased.

Core dependencies: `pandas`, `pydantic`, `requests`, `playwright`, `plotly`, `openai`, `wiley-tdm`, `mineru[torch]` (4.x), `torch`

MinerU downloads its models (~2–3 GB, into `~/.mineru/models`) automatically the first time `transform_text()` runs.
To download them ahead of time, run `mineru-kit models download --tier standard`.

## Installation
Install with [uv](https://github.com/astral-sh/uv):

```bash
uv pip install biomarkit
```

Or with pip:
```python
pip install biomarkit
```