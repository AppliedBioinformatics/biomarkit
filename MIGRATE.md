# Migrating to biomarkit 1.1.0

This guide is written so that an LLM coding assistant (or a person) can update a project that uses **biomarkit 1.0.x**
so that it works with **biomarkit 1.1.0**. Work through the sections in order. Each section says how to detect
whether a project is affected, then shows the exact change.

**Summary of breaking changes**

| # | Area | 1.0.x | 1.1.0 |
|---|---|---|---|
| 1 | Choosing a corpus | `CORPUS_NAME` in `secrets.env`, `build_new_corpus()` | `biomarkit.load_corpus(...)` at the top of every script |
| 2 | PDF conversion | `transform_text(mineru_backend=...)` on MinerU 3 | `transform_text(mineru_tier=...)` on MinerU 4 |
| 3 | `secrets.env` | `CORPUS_NAME`, `MINERU_VLLM_ENDPOINT`, `MINERU_API_KEY`, `MINERU_VIRTUAL_VRAM_SIZE` | `MINERU_VLM_SERVER_URL`, `MINERU_VLM_API_KEY` |
| 4 | Dependency | `mineru[pipeline]>=3.4,<4` | `mineru[torch]>=4.0.12,<5` |
| 5 | Internal imports | `biomarkit.main`, path constants in `biomarkit.config` | `biomarkit.pipeline`, `biomarkit.config.get_corpus()` |

Projects that only call the four top-level functions (`biomarkit.download_corpus`, `transform_text`,
`standardise_text`, plus a corpus call) need sections 1–4. Section 5 only matters for code that imports biomarkit
internals.

---

## Step 0: Find what needs changing

Search the project (excluding virtual environments) for these patterns. Every hit needs a change described below.

| Pattern | Section |
|---|---|
| `build_new_corpus` | 1 |
| `CORPUS_NAME` | 1, 3 |
| `load_corpus(` called with no arguments, or with `corpus_dir=` | 1 |
| `mineru_backend` | 2 |
| `MINERU_VLLM_ENDPOINT`, `MINERU_API_KEY`, `MINERU_VIRTUAL_VRAM_SIZE`, `MINERU_VL_API_KEY` | 3 |
| `mineru[pipeline]`, `mineru>=3`, `mineru<4` | 4 |
| `biomarkit.main` | 5 |
| `SCOPUS_INPUT_CSV_NAME`, `DB_CACHE_FILE_NAME`, `DOWNLOAD_DIR`, `JSON_STRUCT_DIR`, `FINAL_MARKDOWN_DIR`, `REPORT_DIR`, `LOG_DIR`, `CORPUS_DIR` | 5 |
| `create_corpus`, `check_vllm_config`, `MinerUPdfTransformer(` | 5 |

---

## 1. Choosing the corpus: `load_corpus()` replaces `CORPUS_NAME` and `build_new_corpus()`

**What changed.** The active corpus is no longer read from `CORPUS_NAME` in `secrets.env`. A script now selects it by
calling `biomarkit.load_corpus(...)` **before** any other pipeline function. `build_new_corpus()` has been removed;
`load_corpus()` builds a missing corpus itself. Calling `download_corpus()`, `transform_text()` or
`standardise_text()` before `load_corpus()` raises:

```
RuntimeError: No corpus loaded — call biomarkit.load_corpus(...) first.
```

**New signature**

```python
biomarkit.load_corpus(
    corpus: str | Path,                 # a name (-> <BIOMARKIT_DIR>/corpora/<name>) or a path to a corpus folder
    scopus_file: str | Path | None = None,  # Scopus CSV; needed only to build a new corpus
    build: bool | None = None,          # missing corpus: None = ask y/N if interactive, True = build, False = error
) -> list[Publication]                  # publications already in the download cache ([] for a new corpus)
```

**Before (1.0.x)**

```python
import biomarkit
biomarkit.build_new_corpus(name="my_corpus", scopus_file="scopus.csv", set_active=True)
publications = biomarkit.download_corpus()
```

or, relying on `CORPUS_NAME=my_corpus` in `secrets.env`:

```python
import biomarkit
publications = biomarkit.download_corpus()
```

**After (1.1.0)**

```python
import biomarkit
biomarkit.load_corpus("my_corpus", scopus_file="scopus.csv")  # builds it if missing (asks first)
publications = biomarkit.download_corpus()
```

**Rules for rewriting**

- Replace each `build_new_corpus(name=X, scopus_file=Y, ...)` with `load_corpus(X, scopus_file=Y)`. Drop `set_active`;
  `load_corpus()` always makes the corpus active.
- If the project used `CORPUS_NAME` from `secrets.env`, read the value there and add `load_corpus("<that value>")`
  as the first biomarkit call in each script or entry point. Then delete `CORPUS_NAME` from `secrets.env`.
- **Non-interactive code** (batch jobs, cron, CI, scripts run with redirected stdin) must pass `build=True` when the
  corpus might not exist yet, or `build=False` when it must already exist. With the default `build=None`, a missing
  corpus raises `FileNotFoundError` in non-interactive runs instead of prompting.
- `load_corpus()` without arguments, and `load_corpus(corpus_dir=...)` (from development builds), no longer exist.
  Pass the corpus name or path as the first argument.
- To switch corpus mid-script, call `load_corpus()` again with another name. Every later pipeline call uses the new
  corpus.
- The returned list contains only publications that are already downloaded. Code that previously called
  `download_corpus()` just to get `Publication` objects back can use `load_corpus()`'s return value instead.

---

## 2. PDF conversion: MinerU 4 and `mineru_tier`

**What changed.** biomarkit now uses MinerU 4, which replaces MinerU 3's backends with quality tiers.
`transform_text(mineru_backend=...)` has been renamed and remapped to `transform_text(mineru_tier=...)`.

**New signature**

```python
biomarkit.transform_text(
    publications,
    mineru_tier: str = "standard",       # "basic" | "standard" | "advanced"
    mineru_batch_size: int | None = None,
    generate_report: bool = False,
    cleanup_intermediates: bool = True,
)
```

**Mapping**

| 1.0.x `mineru_backend` | 1.1.0 `mineru_tier` | Notes |
|---|---|---|
| `"local-gpu"` (old default) | `"standard"` (new default) | Adds MinerU's vision-language model; MinerU uses the GPU automatically |
| `"local-cpu"` | `"basic"` | Small models only; practical without a GPU |
| `"vllm"` | `"standard"`, plus `MINERU_VLM_SERVER_URL` in `secrets.env` | Remote VLM is configured in `secrets.env`, not by a parameter (see section 3) |
| — | `"advanced"` | New: more VLM compute for hard documents; much slower |

**Before**

```python
publications = biomarkit.transform_text(publications, mineru_backend="local-cpu", mineru_batch_size=25)
```

**After**

```python
publications = biomarkit.transform_text(publications, mineru_tier="basic", mineru_batch_size=25)
```

**Behaviour changes to be aware of (no code change needed)**

- **First run downloads about 2 GB of models** to `~/.mineru/models`. To fetch them ahead of time (e.g. before going
  offline), run `mineru-kit models download --tier standard`.
- **MinerU's own settings** now live in `~/.mineru/config.yaml`. The old `mineru.json` is ignored.
- **`cleanup_intermediates=True`** now keeps each paper's `images/` folder next to its `*_content_list_v2.json`, so
  figure links written by `standardise_text(keep_figures=True)` work. Other MinerU output is deleted as each PDF
  finishes.
- **Existing intermediates stay valid.** JSON files produced by MinerU 3 in `intermediates/` are still read by
  `standardise_text()`, so already-converted papers do not need converting again.
- **New inline span types.** Code that parses `*_content_list_v2.json` itself (outside biomarkit) may now see
  `{"type": "hyperlink", "content": ..., "url": ...}` and `{"type": "code_inline", "content": ...}` spans alongside
  `text` and `equation_inline`. Treat `content` as plain text.
- **Windows:** `mineru[full]` (the LMDeploy engine) can't currently be installed on Windows because of an upstream
  packaging problem. The default llama.cpp engine runs on the GPU and needs no extra install.

---

## 3. `secrets.env`

Edit the project's `secrets.env` (and any `secrets.env.example` or deployment config it is copied from):

| 1.0.x line | 1.1.0 action |
|---|---|
| `CORPUS_NAME=...` | **Delete.** Pass the name to `load_corpus()` instead (section 1). |
| `MINERU_VLLM_ENDPOINT=...` | **Rename** to `MINERU_VLM_SERVER_URL=...` (leave blank to run the VLM locally) |
| `MINERU_API_KEY=...` | **Rename** to `MINERU_VLM_API_KEY=...` (only needed if the server requires a key) |
| `MINERU_VIRTUAL_VRAM_SIZE=...` | **Delete.** MinerU 4 doesn't use it. |
| `MINERU_VL_API_KEY` / `MINERU_VL_MODEL_NAME` in the shell environment | **Unset.** MinerU 4 refuses to run if these conflict with its configuration. biomarkit strips them for its own runs, but other tooling that calls MinerU directly will fail. |

A remote VLM server must now serve **`opendatalab/MinerU2.5-Pro-2605-1.2B`**. Servers set up for MinerU 3's model
need redeploying with the new model.

---

## 4. Dependencies

In the project's `pyproject.toml` / `requirements.txt`:

```diff
- "biomarkit>=1.0,<1.1"
+ "biomarkit>=1.1,<1.2"
- "mineru[pipeline]>=3.4.0,<4"     # remove if pinned directly; biomarkit pulls in MinerU
+ "mineru[torch]>=4.0.12,<5"       # only if the project pins MinerU itself
```

- Python must be **3.12**, as before.
- CUDA builds of `torch==2.9.1` / `torchvision==0.24.1` still come from the PyTorch cu128 index on Windows.
- After upgrading, `python -m biomarkit.text_transformation.utils.generics` prints the installed MinerU version. It
  must be `4.x`. biomarkit raises an `ImportError` with an upgrade hint if MinerU 3 is still installed.

---

## 5. Code that imports biomarkit internals

Skip this section if the project only uses `biomarkit.load_corpus`, `download_corpus`, `transform_text` and
`standardise_text`.

### 5.1 `biomarkit.main` → `biomarkit.pipeline`

```diff
- from biomarkit.main import download_corpus
+ from biomarkit.pipeline import download_corpus      # or simply: from biomarkit import download_corpus
```

The dev entry point is now `python -m biomarkit.pipeline [corpus name or path]`.

### 5.2 Corpus path constants → `get_corpus()`

These module-level constants were removed from `biomarkit.config`:
`CORPUS_NAME`, `CORPUS_DIR`, `SCOPUS_INPUT_CSV_NAME`, `DB_CACHE_FILE_NAME`, `DOWNLOAD_DIR`, `JSON_STRUCT_DIR`,
`FINAL_MARKDOWN_DIR`, `REPORT_DIR`, `LOG_DIR`.

Use `biomarkit.config.get_corpus()`, which returns the active corpus's paths. Call it **at the point of use**, after
`load_corpus()`. Never call it at import time or in a default argument, because it raises until a corpus is loaded,
and it changes when the corpus is switched.

| Removed constant | Replacement |
|---|---|
| `CORPUS_DIR` | `get_corpus().root` |
| `SCOPUS_INPUT_CSV_NAME` | `get_corpus().scopus_csv` |
| `DB_CACHE_FILE_NAME` | `get_corpus().db` |
| `DOWNLOAD_DIR` | `get_corpus().download_dir` |
| `JSON_STRUCT_DIR` | `get_corpus().json_dir` |
| `FINAL_MARKDOWN_DIR` | `get_corpus().final_md_dir` |
| `REPORT_DIR` | `get_corpus().report_dir` |
| `LOG_DIR` | `get_corpus().log_dir` |
| `CORPUS_NAME` | `get_corpus().root.name` |

```diff
- from biomarkit.config import DB_CACHE_FILE_NAME
- conn = sqlite3.connect(DB_CACHE_FILE_NAME)
+ from biomarkit.config import get_corpus
+ conn = sqlite3.connect(get_corpus().db)
```

`CORPORA_DIR`, `BASE_DIR`, `TMP_DIR` and all API-key settings are unchanged.

### 5.3 Other removed or changed internals

| 1.0.x | 1.1.0 |
|---|---|
| `text_download.utils.generics.build_new_corpus()` / `create_corpus()` | `biomarkit.load_corpus(..., build=True)`, or the lower-level `generics.resolve_corpus_path(corpus)` + `generics.build_corpus(path, scopus_file)` |
| `text_transformation.utils.generics.check_vllm_config()` | `check_vlm_server_config()`, which returns `True` if a remote VLM is configured |
| `check_mineru()` returned the path to `mineru.exe` | returns the installed MinerU version string, and raises `ImportError` if it's older than 4 |
| `prepare_bulk_transformation(mineru_backend=...)` | `prepare_bulk_transformation(mineru_tier=...)` |
| `MINERU_BACKEND_CHOICES` (generics) | `biomarkit.config.MINERU_TIER_CHOICES` |
| `MinerUPdfTransformer(pubs, mineru_backend=..., batch_size=...)` | `MinerUPdfTransformer(pubs, mineru_tier=..., batch_size=..., cleanup=True)`. It runs MinerU in a worker process (`converters/mineru_worker.py`) instead of calling the `mineru` CLI |
| `synchronise_publishers(df, ...)` dropped rows with any missing field (via `remove_imperfect_rows`) | `remove_imperfect_rows()` only drops rows missing DOI, title or year (and duplicate DOIs). See section 6 |

### 5.4 Tests

In biomarkit's own test suite, `tests/conftest.py` provides an autouse `active_corpus` fixture that gives each test a
temporary corpus. Projects that test code built on biomarkit need the equivalent: call
`biomarkit.config.set_active_corpus(tmp_path)` in a fixture, and reset `biomarkit.config._active_corpus = None`
afterwards. Replace any `patch("biomarkit.config.DB_CACHE_FILE_NAME", ...)`-style patches with this fixture.

---

## 6. Download behaviour changes (no code change required)

These change results, not APIs. Check them if the project compares counts between runs.

- **More papers are attempted.** Scopus rows with a blank Publisher field (or blank Abstract) are no longer dropped.
  Only rows missing a DOI, title or year are skipped. Expect noticeably more publications from `download_corpus()`
  on the same CSV.
- **Publisher inferred from the DOI.** `download_corpus(infer_publisher_from_doi=True)` (the default) routes papers
  with a missing or unrecognised publisher to a client based on the DOI prefix (e.g. `10.1016` → Elsevier). Pass
  `False` to turn this off. Papers with no determinable publisher get `publisher == "unknown"` and are tried through
  the open-access routes only. Code that groups by `Publication.publisher` should expect the value `"unknown"`.
- **Bad rows are skipped, not fatal.** A Scopus row that fails `Publication` validation (e.g. an unusual DOI format) is
  now skipped with a warning, instead of aborting the whole run.
- **Frontiers and MDPI** fall back to the publisher's own PDF URL when Unpaywall only lists a landing page, so fewer
  papers fail with "Timeout … waiting for event 'download'".

---

## Checklist

- [ ] No hits remain for the Step 0 patterns.
- [ ] Every script calls `biomarkit.load_corpus(...)` before other biomarkit calls; non-interactive scripts pass
      `build=True` or `build=False`.
- [ ] `secrets.env` has no `CORPUS_NAME`, and the MinerU variables are renamed or removed (section 3).
- [ ] MinerU 4.x is installed (`python -m biomarkit.text_transformation.utils.generics` prints `4.`).
- [ ] `transform_text` calls use `mineru_tier`.
- [ ] The project's own tests pass.