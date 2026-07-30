# text_transformation — Developer Reference

Converts downloaded PDFs and XML files into standardized Markdown. Elsevier XMLs are parsed directly; all other PDFs are converted locally via MinerU (GPU required). Runs are resumable via the shared SQLite cache.

---

## `controller/`

Cross-references each `Publication` against the cache to populate all three filepath fields, then sorts publications into three lists:

- `needs_conversion` — `publication_filepath` set, no markdown yet. Forwarded to the converters.
- `needs_processing` — raw markdown exists but final markdown does not. Reserved for a future post-processing step; currently passed through unchanged.
- `fully_processed` — all filepaths set. Skipped entirely.

Also discards publications that were not downloaded (no `publication_filepath`) and infers `document_type = XML` for papers whose source file has a `.xml` extension.

---

## `converters/ABC/converter.py`

Abstract base class (`Converter`) shared by all converters. Provides:

- Output path construction: `RAW_MARKDOWN_DIR/<stem>/<stem>.md`.
- `convert_all()` — iterates publications, calls `convert(pub)`, updates `pub.raw_md_filepath` on success, writes the path to the cache via `update_raw_md_filepath`, and logs pass/fail counts.

Subclasses implement only `convert(pub) -> Path | None`.

---

## `converters/elsevier_xml_to_md.py`

Parses Elsevier full-text XML into Markdown. Handles:

- Document structure: title, authors, abstract, keywords, body sections, and references, with heading levels preserved.
- LaTeX and MathML formula conversion to inline Markdown math.
- CALS table parsing to Markdown table format.
- Inline markup: bold, italic, superscript, subscript.
- Orphaned figures and tables collected under explicit `# Figures` and `# Tables` headings.

Output: `RAW_MARKDOWN_DIR/<stem>/<stem>.md`.

---

## `converters/mineru_pdf_to_md.py`

Converts PDFs to Markdown using the MinerU CLI (OpenDataLab), a layout-aware PDF parser.

Resolves the MinerU executable (`.venv/Scripts/mineru.exe` or global PATH), stages all pending PDFs into a temporary directory, and converts them in a single `subprocess` call (`-p <dir>`), so MinerU loads its models once per run rather than once per PDF. OCR language is pinned to English (`-l en`; the CLI defaults to Chinese). `convert()` then verifies each publication's output individually — a partially failed batch still caches the publications that converted. PDFs whose output `.md` already exists on disk (e.g. from a run interrupted before the cache write) are not re-staged; their existing files are cached directly. MinerU writes output to `RAW_MARKDOWN_DIR/<stem>/auto/<stem>.md`.

Setting `MINERU_VIRTUAL_VRAM_SIZE` in `secrets.env` (integer GB) overrides MinerU's auto-detected VRAM budget to raise inference batch sizes on larger GPUs.

**Remote inference (`mineru_endpoint="vllm"`):** constructed with `mineru_endpoint="vllm"`, the converter swaps the batch command to the `vlm-http-client` backend (`-b vlm-http-client -u $MINERU_VLLM_ENDPOINT`), which makes the CLI a thin client against a remote vLLM server hosting the MinerU VLM model. The API key is passed to the subprocess as `MINERU_VL_API_KEY`, which MinerU's HTTP client sends as a `Bearer` Authorization header. The `-l` flag is omitted (pipeline-only). In this mode MinerU writes to `RAW_MARKDOWN_DIR/<stem>/vlm/<stem>.md` instead of `<stem>/auto/`, and `_build_output_path()` follows suit. The endpoint URL must not end with a trailing slash — MinerU reduces `http://host:port[/path]` to its base and appends `/v1/chat/completions` itself, but preserves (and then double-suffixes) a slash-terminated path.

> Note: MinerU writes to a subdirectory `auto/` (local) or `vlm/` (remote) — one level deeper than the XML converter.

---

## `utils/generics.py`

Pre-flight checks run by `prepare_bulk_transformation(mineru_endpoint)` before any conversion begins:

- Validates `mineru_endpoint` (`"local"` or `"vllm"`).
- Creates `RAW_MARKDOWN_DIR` and `FINAL_MARKDOWN_DIR` if absent.
- Logs current cache state (publications with raw/final markdown already present).
- Verifies a CUDA GPU is available via PyTorch; locates the MinerU executable. With
  `mineru_endpoint="vllm"` a missing GPU is only a warning (inference is remote), and
  `check_vllm_config()` instead affirms `MINERU_VLLM_ENDPOINT` and `MINERU_API_KEY` are
  filled in `secrets.env`, raising `ValueError` before any conversion if either is blank.

`finalise_transformation(publications)` — validates internal consistency of the output list and returns it for handoff to `chunkify`.

---

## `visualisation/conversion_report.py`

Generates a timestamped Plotly HTML report (`corpora/<CORPUS_NAME>/reports/conversion_report_<timestamp>.html`) after each run. Charts include:

- Overall conversion status by document type (XML vs PDF).
- Conversion status by publisher and by publication year.
- Output markdown file size distribution (successful conversions only).
- Failed conversions broken down by publisher and document type.
- Run breakdown donut (Converted / Failed / Pre-cached split).

---

## Known limitations

- `needs_processing` publications (raw markdown present, no final markdown) are passed downstream silently with no post-processing applied. This bucket exists for a planned standardisation step that is not yet implemented.
- MinerU output paths include an `auto/` subdirectory that the XML converter does not produce, making the two output layouts inconsistent on disk.