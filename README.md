# Biomarkit

A tool for downloading full-text scientific publications and converting them into a standardised Markdown format.

Starting from a Scopus query export, biomarkit downloads full-text papers, converts them to raw Markdown, then
cleans and standardises each document into a final Markdown file suitable for downstream processing
(e.g. chunking, RAG, or LLM-derived knowledge extraction).

---

## Pipeline Overview

```
Scopus CSV → [text_extraction] → [text_transformation] → [standardisation] → standardised .md files
```

---

## Modules

### `text_extraction`

Downloads full-text PDFs and XML files for publications listed in a Scopus query CSV. Filters and standardises the Scopus input, routes each paper through a two-stage API download process (open-source routes first — arXiv, bioRxiv/medRxiv, ChemRxiv, then Unpaywall — followed by publisher-specific clients in parallel), and caches results to an SQLite database for resumable runs. Outputs HTML download summary reports.

See [docs/devs/text_extraction.md](docs/devs/text_extraction.md) for full developer documentation.

---

### `text_transformation`

Converts downloaded PDFs and XML files into Markdown format. Elsevier XMLs are parsed directly; all other PDFs are converted locally via MinerU (CUDA GPU required). Runs are resumable via the shared SQLite cache. Outputs a timestamped HTML conversion report.

See [docs/devs/text_transformation.md](docs/devs/text_transformation.md) for full developer documentation.

---

### `standardisation`

Cleans raw Markdown and standardises it into its final form: normalises headings, classifies sections
(via an LLM-backed section classifier), splits merged abstracts, strips boilerplate, and reassembles each
document into a standardised Markdown file.

---

## Running the Pipeline

```python
# Full local run
from main import extract_text, transform_text, standardise_text

publications = extract_text()
publications = transform_text(publications)
standardise_text(publications)
```

PDF conversion runs locally via MinerU and requires a CUDA-capable GPU. Alternatively,
`transform_text(publications, mineru_endpoint="vllm")` delegates MinerU inference to a remote vLLM
server hosting the MinerU VLM model (set `MINERU_VLLM_ENDPOINT` and `MINERU_API_KEY` in `secrets.env`).

---

## Corpus Layout

All inputs and outputs live under `corpora/<corpus_name>/`. Select the active corpus by setting
`CORPUS_NAME` in `config.py`. Each corpus folder contains:

```
corpora/
└── <corpus_name>/
    ├── scopus.csv       # Scopus query export (input — place this here)
    ├── manuscripts/     # Downloaded full-text PDFs/XMLs
    ├── markdowns/       # Raw Markdown converted from PDFs/XMLs
    ├── results/         # Final standardised Markdown
    ├── reports/         # HTML output reports
    ├── logs/            # Run logs
    └── sqlite.db        # SQLite cache for this corpus
```

Everything except `scopus.csv` is created automatically on the first run.

---

## Configuration

Key settings are in `config.py`:

| Setting | Description |
|---|---|
| `CORPUS_NAME` | Name of the active corpus folder under `corpora/` |
| `MAX_THREADS` | Max parallel threads for API downloads |
| `LLM_BASE_URL` | OpenAI-compatible endpoint for the fallback section classifier (defaults to local [Ollama](https://ollama.com)) |
| `LLM_MODEL_NAME` | Model used by the fallback classifier (default `llama3.2:3b`) |

Secrets (API keys) are read from `secrets.env` — see `secrets.env.example`.

---

## Requirements

- Python 3.12–3.13
- A CUDA-capable GPU (for PDF conversion via MinerU)
- Optional: [Ollama](https://ollama.com/download) running `llama3.2:3b` (~2 GB), used as an LLM fallback when classifying ambiguous section headings. Without it the pipeline still runs; ambiguous headings are kept as body text.
- Core dependencies: `pandas`, `pydantic`, `requests`, `playwright`, `plotly`, `openai`, `wiley-tdm`, `mineru[pipeline]`, `torch` (CUDA 12.8)

Install with [uv](https://github.com/astral-sh/uv):

```bash
uv sync
```