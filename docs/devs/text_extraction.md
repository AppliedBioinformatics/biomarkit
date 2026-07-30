# text_extraction — Developer Reference

Downloads full-text PDFs and XML files for publications listed in a Scopus query CSV. Filters and standardises the Scopus input, routes each paper through a two-stage API download process (open-source routes first — arXiv, bioRxiv/medRxiv, ChemRxiv, then Unpaywall — followed by publisher-specific clients in parallel), and caches results to an SQLite database for resumable runs.

![high-level-overview](/docs/static/text_extraction_overview.png)

---

## `basemodels/publication.py`

Pydantic model (`Publication`) that represents a single paper throughout the entire pipeline. Holds DOI, title, publisher, year, and document type (PDF/XML/HTML), plus optional file paths that are populated as the paper progresses through each stage (`publication_filepath`, `raw_md_filepath`, `final_md_filepath`). Validates DOI format (regex) and year (1900 – present+1) on creation. Exposes `is_cached`, `is_converted`, and `is_processed` properties derived from filepath presence.

---

## `filter/`

Loads the raw Scopus CSV export and prepares it for processing:

- Reads the CSV and retains only the four required columns (`Title`, `Year`, `DOI`, `Publisher`).
- Drops any rows with missing values.
- Standardises publisher names to a canonical form using a configurable dictionary (`publisher_map.py`), creating a `PublisherGroup` column used for API routing.
- Converts each remaining row into a `Publication` object.

To add support for a new publisher, add an entry to `filter/publisher_map.py` mapping the canonical name to a list of known Scopus variants.

---

## `database/`

SQLite-backed cache (`corpora/<CORPUS_NAME>/sqlite.db`) that persists download state across runs. Schema stores DOI, source API, and file paths for each pipeline stage. Key operations:

- `create_database` — initialises the schema on first run.
- `insert_row` — records a successful download.
- `update_raw_md_filepath` — updates the cache when a paper is converted to markdown.
- `get_row_for_doi` — looks up a DOI and returns its cached state as a dict.

To reset the pipeline to a clean state for a corpus, delete `corpora/<CORPUS_NAME>/sqlite.db` and all files in the corpus `manuscripts/` folder.

---

## `controller/`

Orchestrates the pre-download stage. Cross-references each `Publication` DOI against the cache and populates `publication_filepath` for any previously downloaded papers. Returns two lists — cached publications (skipped) and uncached publications (forwarded to the API router). Also validates that all `Publication` objects are well-formed before routing begins.

---

## `apis/`

Handles all external downloads. Structured as an abstract base class with publisher-specific subclasses.

### `abc/publisher_api.py`

Abstract base class (`PublisherApi`) shared by all clients. Provides:

- URL connectivity test on instantiation (raises `ConnectionError` if unreachable).
- Per-client file logging to `LOG_DIR/<name>_client.log`.
- Filepath generation with a random 10-digit suffix to avoid collisions.
- `_attempt_download` — standardised error handling for HTTP errors, SSL errors, timeouts, connection errors, and redirect loops.
- `_cache_successful_download` — writes a successful download to the SQLite cache.
- `download_all_papers` — iterates publications, calls `download_paper(doi)`, updates `publication_filepath`, and caches on success.

Subclasses must implement `download_paper(doi) -> Path | None`.

### `router.py` — `ApiRouter`

Two-stage routing:

1. Passes all uncached publications to the open-source client (`opensource.py`) — direct arXiv, bioRxiv/medRxiv and ChemRxiv routes, then the Unpaywall API.
2. Groups remaining failures by publisher and dispatches each group to the matching client in parallel (`ThreadPoolExecutor`, `MAX_THREADS`).

Asserts that the total publication count is preserved end-to-end (finished + unfinished == input).

### `clients/`

| Client | Format | Notes |
|---|---|---|
| `opensource.py` | PDF | Tried first for all papers. Direct preprint routes (arXiv → bioRxiv/medRxiv → ChemRxiv), then Unpaywall. Filenames are prefixed with the route that succeeded. |
| `elsevier.py` | XML | Elsevier TDM API. Sets `document_type = XML` on all handled publications. |
| `wiley.py` | PDF | Uses the `wiley-tdm` package. |
| `springer.py` | PDF | HTTP download via `requests`. |
| `frontiers.py` | PDF | HTTP download via `requests`. |
| `mdpi.py` | PDF | HTTP download via `requests`. |

### `map.py`

Dictionary mapping canonical publisher names to client classes. Used by the router to instantiate nodes. Add new publishers here alongside a new client in `clients/`.

---

## `utils/`

General-purpose helpers:

- `setup_logging` / `setup_run` — logging config and corpus directory initialisation (`logs/`, `reports/`, `manuscripts/`).
- `validate_pdf_file` / `validate_xml_file` — basic file integrity checks.
- `build_plotly_report` — shared Plotly HTML report scaffold used by both visualisation modules.
- `clean_publications` — removes any stale publication files from `DOWNLOAD_DIR` that are no longer referenced by the cache.

---

## `visualisation/`

Generates HTML reports (via Plotly) saved to the corpus `reports/` folder:

- `text_extraction_report.py` — Combined report generated after downloads complete. Contains Scopus input summary charts (publisher frequency, grouped frequency, cumulative coverage) and download result charts (cache status, downloads per API, per-publisher breakdown, publications by year).
- `scopus_query_report.py` — Private plot helper functions for Scopus input charts.
- `download_report.py` — Private plot helper functions for download result charts.

---

## How-tos

### Add or edit publisher groups

Edit `filter/publisher_map.py`. Each key is the canonical publisher name used throughout the pipeline; each value is a list of raw Scopus strings that should map to it.

### Add a new API client

1. Create a new file in `apis/clients/` with a class that inherits from `PublisherApi`.
2. Implement `download_paper(doi: str) -> Path | None` with all client-specific logic.
3. Set `self.name` to match the canonical publisher name in `publisher_map.py`.
4. Register the class in `apis/map.py` so the router can instantiate it.

---

## Known limitations

- Papers that fail all APIs are passed downstream with `publication_filepath = None`. The `text_transformation` controller discards them, but there is no dedicated report of permanently undownloadable DOIs beyond the download summary HTML.
- Springer articles download as PDF (no XML support), producing lower-quality markdown than Elsevier XML.
- `logging/logger.py` exists as a subpackage but is not referenced anywhere — likely a legacy file.