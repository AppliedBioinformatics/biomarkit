# First-Time Setup Guide

This guide walks you through setting up the software from scratch.

---

## 1. Prerequisites

You will need the following installed on your computer:

- **Python 3.12 or 3.13** -- download from [python.org](https://www.python.org/downloads/)
- **uv** -- a Python project manager. Install from [github.com/astral-sh/uv](https://github.com/astral-sh/uv)
- **Git** -- download from [git-scm.com](https://git-scm.com/downloads)

To check these are installed, open a terminal and run:

```
python --version
uv --version
git --version
```

Each should print a version number. If any show an error, install the missing tool before continuing.

---

## 2. Download the Project

Open a terminal, navigate to the folder where you want to store the project, and run:

```
git clone <repository-url>
cd wheatis_llm
```

Replace `<repository-url>` with the URL of the GitHub repository.

---

## 3. Install Dependencies

From the project folder, run:

```
uv sync
```

This creates a virtual environment (`.venv` folder) and downloads all required packages.

---

## 4. Create Your secrets.env File

All sensitive settings (API keys, account details) are stored in a single file called `secrets.env` in the project root folder. This file is not tracked by Git, so you need to create it yourself.

Create a new file called `secrets.env` in the project root (the same folder as `config.py`) and add the following:

```
# Your email address (required for the Unpaywall API).
USER_EMAIL=

# Publisher API keys -- only needed for the publishers you want to download from.
WILEY_TDM_TOKEN=
SPRINGER_API_KEY=
ELSEVIER_API_KEY=

# Hugging Face token (required for accessing gated models).
HF_TOKEN=
```

Fill in the values that apply to you. Any lines you leave blank will simply be ignored -- the software will skip features that require missing keys.

## 5. Prepare Your Input Data

The software reads a CSV file exported from [Scopus](https://www.scopus.com/) as its input. For more information on 
how to generate this, please see the documentation [here](modules/text_extraction.md#generating-your-input-scopus-query)

Each dataset ("corpus") lives in its own folder under `corpora/`, holding its inputs, outputs, cache, reports and logs.

1. Export your search results from Scopus as a CSV file.
2. Create a folder for your corpus, e.g. `corpora/my_corpus/`, and place the CSV inside it named `scopus.csv`.
3. Open `config.py` and set `CORPUS_NAME` to your folder name:

```python
CORPUS_NAME = "my_corpus"
```

All other subfolders (`manuscripts/`, `markdowns/`, `results/`, `reports/`, `logs/`) and the `sqlite.db` cache are created automatically on the first run.

---

## 6. PDF Conversion Requirements

The software converts downloaded PDFs into markdown text using [MinerU](https://github.com/opendatalab/MinerU),
which runs locally and requires a computer with a CUDA-capable GPU.

---

## 7. LLM Fallback Setup (Optional)

During standardisation, most section headings are classified by regex rules. Headings the rules cannot resolve
are sent to a small local LLM served by [Ollama](https://ollama.com). This step is optional — if Ollama is not
installed or not running, the software warns you and continues without the fallback (unresolved headings are
kept as body text).

To enable it:

1. Install Ollama from [ollama.com/download](https://ollama.com/download) (on Windows: `winget install Ollama.Ollama`).
2. Download the model (~2 GB, one-time):

```
ollama pull llama3.2:3b
```

That's it — the software checks for the model automatically at the start of each standardisation run. To use a
different model or endpoint, set `LLM_MODEL_NAME` / `LLM_BASE_URL` in `secrets.env`.

---

## 8. Run the Software

Currently, a full pipeline run can be triggered by running:

```
uv run python main.py
```

---

## 9. Caching

The program automatically creates a database (`sqlite.db`) inside each corpus folder that tracks which papers have been downloaded. This means:

- If the program crashes or is interrupted, it attempts to pick up where it left off.
- If you change your input file, previously downloaded papers are not re-downloaded.

### Resetting the cache

To start a corpus completely fresh, delete:

1. All files in the `corpora/<CORPUS_NAME>/manuscripts/` folder.
2. The `corpora/<CORPUS_NAME>/sqlite.db` file.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `uv sync` fails | Make sure `uv` is installed and you are running the command from the project root folder. |
| "Module not found" errors | Run commands with `uv run` (e.g. `uv run python main.py`) so the virtual environment is used. |
| API key errors | Check that `secrets.env` exists in the project root and your keys are correct. |