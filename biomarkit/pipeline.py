from __future__ import annotations
import logging
from time import perf_counter
from pathlib import Path

from biomarkit.text_download.basemodels.publication import Publication

def _can_prompt() -> bool:
    """True when input() can reach a user: an interactive terminal or a Jupyter kernel."""
    import sys
    return sys.stdin is not None and sys.stdin.isatty() or "ipykernel" in sys.modules

# High-level functions.
def load_corpus(corpus: str | Path, scopus_file: str | Path | None = None,
                build: bool | None = None) -> list[Publication]:
    """
    Set the active corpus for this session, building it first if it doesn't exist, and return
    Publication objects for every publication already in its download cache.

    All other pipeline functions (download_corpus, download_dois, transform_text, standardise_text)
    read and write the corpus loaded here, so call this first.

    Parameters
    ----------
    corpus : str | Path
        A corpus name (resolved to <BIOMARKIT_DIR>/corpora/<name>) or a path to a corpus folder.
    scopus_file : str | Path | None, default None
        Scopus export CSV, copied into the corpus if it has no scopus.csv yet. Not needed for a
        corpus whose publications come from a DOI list (download_dois).
    build : bool | None, default None
        What to do if the corpus folder doesn't exist. None asks for confirmation when running
        interactively (terminal or notebook) and raises otherwise. True builds without asking
        (use this in batch jobs). False never builds and raises FileNotFoundError.

    Returns
    -------
    list[Publication]
        One Publication per DOI found in the cache, with metadata from the Scopus CSV and
        filepaths populated wherever they exist in the cache. Empty for a new corpus, and for a
        corpus without a scopus.csv (call download_dois again to get its cached publications).
    """
    from pydantic import ValidationError
    from biomarkit.config import set_active_corpus
    from biomarkit.text_download.filter import filter_scopus_csv as ftr
    from biomarkit.text_download.database.database import get_all_cached_dois, get_row_for_doi, _to_absolute
    from biomarkit.text_download.utils.generics import resolve_corpus_path, build_corpus

    corpus_dir = resolve_corpus_path(corpus)

    if not corpus_dir.exists():
        if build is False:
            raise FileNotFoundError(f"Corpus not found at {corpus_dir}.")
        if build is None:
            no_prompt_error = FileNotFoundError(
                f"Corpus not found at {corpus_dir}. Pass build=True to build it without confirmation."
            )
            if not _can_prompt():
                raise no_prompt_error
            try:
                answer = input(f"Corpus not found at {corpus_dir}. Build a new corpus there? [y/N] ")
            except EOFError:
                # stdin looked interactive but isn't (e.g. redirected from NUL on Windows).
                raise no_prompt_error from None
            if answer.strip().lower() not in ("y", "yes"):
                raise FileNotFoundError(f"Corpus not built at {corpus_dir}.")
        build_corpus(corpus_dir, scopus_file)
    elif scopus_file is not None:
        build_corpus(corpus_dir, scopus_file)

    paths = set_active_corpus(corpus_dir)
    logging.info(f"Active corpus: {paths.root}")

    if not paths.db.exists():
        return []

    cached_dois = set(get_all_cached_dois(paths.db))
    if not cached_dois:
        return []

    if not paths.scopus_csv.exists():
        logging.info("Corpus has no scopus.csv - call download_dois() with its DOI list to get its publications.")
        return []

    raw_df = ftr.load_scopus_csv(paths.scopus_csv)
    df = ftr.remove_imperfect_rows(df=raw_df)
    df = ftr.synchronise_publishers(df=df)
    df = df[df["DOI"].isin(cached_dois)]

    publications = ftr.build_publication_objects(df=df)

    for pub in publications:
        row = get_row_for_doi(pub.doi, db_path=paths.db)
        if row is None:
            continue
        for field in ("publication_filepath", "content_json_filepath", "final_md_filepath"):
            if not row.get(field):
                continue
            try:
                setattr(pub, field, _to_absolute(row[field], paths.db))
            except ValidationError:
                logging.warning(f"{pub.doi}: cached {field} {row[field]} not found on disk - treating as missing.")

    return publications

def download_corpus(check_opensource: bool = True, generate_report: bool = False,
                    infer_publisher_from_doi: bool = True) -> list[Publication]:
    """
    Download full-text PDFs and XMLs for all publications in the active corpus's Scopus CSV.

    Each DOI is routed through a two-stage process: open-access routes (PMC BioC XML, arXiv, bioRxiv,
    ChemRxiv, Unpaywall) are tried first when check_opensource=True, then publisher APIs
    (Elsevier, Wiley, Springer, MDPI, Frontiers, etc.) handle the remainder. Previously
    downloaded publications are loaded from the SQLite cache and download for these is not
    attempted. An HTML report is always written to the corpus reports folder on completion.

    Parameters
    ----------
    check_opensource : bool, default True
        When True, attempt open-access routes before falling back to publisher APIs.
        Set to False to skip directly to publisher specific APIs.
    infer_publisher_from_doi : bool, default True
        When True, papers whose Scopus publisher is missing or not recognised get a
        publisher inferred from their DOI prefix (e.g. 10.1016 -> Elsevier), so they can
        be routed to that publisher's API client. A recognised Scopus publisher is never
        overridden. Papers without a known publisher still get the open-access routes.

    Returns
    -------
    list[Publication]
        All publications from the Scopus CSV, including those loaded from cache.
        Each object carries DOI, title, publisher, year, document type, and the
        filepath of the downloaded PDF or XML (None if download failed).
    """

    from biomarkit.config import get_corpus
    from biomarkit.text_download.filter import filter_scopus_csv as ftr

    function_start = perf_counter()
    _setup_download()

    scopus_csv = get_corpus().scopus_csv
    if not scopus_csv.exists():
        raise FileNotFoundError(
            f"No Scopus CSV found for corpus at {scopus_csv}. "
            f"Place your Scopus export there, or use download_dois() for a DOI list."
        )

    return _download(ftr.load_scopus_csv(scopus_csv), check_opensource, generate_report,
                     infer_publisher_from_doi, function_start)

def download_dois(dois: str | Path | list[str], check_opensource: bool = True, generate_report: bool = False,
                  infer_publisher_from_doi: bool = True) -> list[Publication]:
    """
    Download full-text PDFs and XMLs for a list of DOIs into the active corpus, without a Scopus export.

    Title, year, publisher and abstract are fetched from Crossref (https://api.crossref.org), then the
    publications go through the same routing as download_corpus(). DOIs Crossref can't resolve (e.g.
    arXiv/DataCite DOIs) are logged and dropped. Previously downloaded DOIs are loaded from the cache,
    so re-running with the same list resumes a corpus.

    Parameters
    ----------
    dois : str | Path | list[str]
        A text file with one DOI per line (blank lines and '#' comments skipped), or a list of DOI
        strings. https://doi.org/ and doi: prefixes are stripped.
    check_opensource : bool, default True
        When True, attempt open-access routes before falling back to publisher APIs.
    generate_report : bool, default False
        When True, write an HTML download report to the corpus reports folder.
    infer_publisher_from_doi : bool, default True
        When True, papers whose Crossref publisher is not recognised get a publisher inferred from
        their DOI prefix (e.g. 10.1016 -> Elsevier), so they can be routed to that publisher's API client.

    Returns
    -------
    list[Publication]
        All resolved publications, including those loaded from cache, with publication_filepath set
        where a download exists.
    """
    from biomarkit.config import get_corpus
    from biomarkit.text_download.filter.crossref_metadata import read_dois, fetch_crossref_metadata

    get_corpus()  # fail before querying Crossref if no corpus is loaded
    function_start = perf_counter()
    _setup_download()

    doi_list = read_dois(dois)
    df = fetch_crossref_metadata(doi_list)
    if df.empty:
        raise ValueError(f"None of the {len(doi_list)} DOI(s) could be resolved by Crossref.")

    return _download(df, check_opensource, generate_report, infer_publisher_from_doi, function_start)

def _setup_download() -> None:
    """Logging, corpus folders and cache, and removal of downloads missing from the cache."""
    from biomarkit.text_download.utils.generics import setup_logging, setup_run, clean_publications

    setup_logging(level=logging.INFO)
    setup_run()
    clean_publications()

def _download(raw_df, check_opensource: bool, generate_report: bool, infer_publisher_from_doi: bool,
              function_start: float) -> list[Publication]:
    """
    Shared download stage for download_corpus() and download_dois(). raw_df has the columns load_scopus_csv()
    produces (Title, Year, DOI, Publisher and optionally Abstract).
    """
    from biomarkit.text_download.filter import filter_scopus_csv as ftr
    from biomarkit.text_download.controller.controller import Controller
    from biomarkit.text_download.apis.router import ApiRouter
    from biomarkit.text_download.visualisation.text_extraction_report import build_text_download_report

    # Filter + Synchronize. (Can add more steps here)
    df = ftr.remove_imperfect_rows(df=raw_df)
    df = ftr.synchronise_publishers(df=df, infer_from_doi=infer_publisher_from_doi)

    # Convert all remaining rows into standardized publication objects.
    publications = ftr.build_publication_objects(df=df)

    # Pass publication objects to the controller.
    controller = Controller(publication_list=publications)

    # Check to see if papers are already downloaded and pass the rest to the api client router.
    uncached_pubs, cached_pubs = controller.prepare_publications_for_router()

    # Instantiate API router and handle paper downloads.
    router = ApiRouter(uncached_pubs)
    router.try_opensource = check_opensource

    # Time the open-source download stage (arXiv/bioRxiv/ChemRxiv direct routes + Unpaywall).
    opensource_start = perf_counter()
    router.throw_at_opensource()
    opensource_seconds = perf_counter() - opensource_start

    # Time the remaining API queries (all publisher nodes combined).
    other_apis_start = perf_counter()
    results = router.disperse_to_nodes()
    other_apis_seconds = perf_counter() - other_apis_start

    all_publications = router.finalise_publication_list(results)

    # Build combined text-extraction report.
    if generate_report:
        build_text_download_report(
            df=df, downloaded_pubs=all_publications, cached_pubs=cached_pubs,
            timings={
                "opensource": opensource_seconds,
                "other_apis": other_apis_seconds,
                "total": perf_counter() - function_start,
            },
        )

    # Report timing metrics.
    total_seconds = perf_counter() - function_start
    logging.info(
        "extract_text timing — open-source routes: %.2fs | other APIs: %.2fs | total: %.2fs",
        opensource_seconds, other_apis_seconds, total_seconds,
    )

    return all_publications + cached_pubs

def transform_text(
    publications: list[Publication],
    mineru_tier: str = "standard",
    mineru_batch_size: int | None = None,
    generate_report: bool = False,
    cleanup_intermediates: bool = True,
    xml_workers: int | None = None,
) -> list[Publication]:
    """
    Convert downloaded PDFs and XMLs into structured JSON content-list files.

    Elsevier and PMC BioC XMLs are parsed directly; all other PDFs are processed via MinerU.
    Publications whose JSON output already exists on disk are skipped and passed
    through unchanged. An HTML conversion report is always written to the corpus
    reports folder on completion.

    Parameters
    ----------
    publications : list[Publication]
        Output of download_corpus(). Publications without a local file
        (publication_filepath is None) are silently skipped.
    mineru_tier : {"basic", "standard", "advanced"}, default "standard"
        MinerU 4 parsing tier. "basic" uses small models only (OCR, layout, formulas,
        tables) and runs acceptably on CPU. "standard" adds the MinerU VLM for complex
        layouts and is best run on a GPU. "advanced" spends more VLM compute on hard
        documents. MinerU picks the device and VLM engine itself. If MINERU_VLM_SERVER_URL
        is set in secrets.env, VLM inference is sent to that remote server instead.
    mineru_batch_size : int | None, default None
        Number of PDFs per MinerU worker process (models load once per batch). None sends all pending
        PDFs in a single call. Set a positive integer to process in sequential
        chunks — each completed chunk is cached before the next begins.
    cleanup_intermediates : bool, default True
        When True, non-essential MinerU output files (debug PDFs, raw markdown,
        model metadata, extracted images) are deleted from the intermediates folder
        after conversion, keeping only the *_content_list_v2.json files.
        Set to False to preserve all MinerU output for debugging.
    xml_workers : int | None, default None
        Number of processes used to parse XMLs (Elsevier and BioC). None uses all CPU cores but one; 1 parses sequentially.
        On Windows and macOS a script that calls transform_text() must do so under ``if __name__ == "__main__":``
        because worker processes re-import the calling script.

    Returns
    -------
    list[Publication]
        All input publications, including those already cached from a previous run.
        Each object has content_json_filepath set if conversion succeeded.
    """

    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation, finalise_transformation, cleanup_intermediate_files
    from biomarkit.text_transformation.controller.controller import Controller
    from biomarkit.text_transformation.converters.elsevier2json import ElsevierXmlTransformer
    from biomarkit.text_transformation.converters.bioc2json import BioCXmlTransformer
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    from biomarkit.text_transformation.visualisation.conversion_report import build_conversion_report

    # Send publications to text transformation controller to categorize them for processing based on cached state.
    controller = Controller(publication_list=publications)
    controller.prepare_publications()

    # Build JSON structure files for each publication if they have not already been generated by a previous run.
    xmls_to_process = [pub for pub in controller.needs_transformation if pub.document_type == "XML"]
    # BioC XMLs from the open-source client's PMC route carry the "bioc_" filename prefix; every other XML is Elsevier.
    bioc_xmls = [pub for pub in xmls_to_process if pub.publication_filepath.name.startswith("bioc_")]
    elsevier_xmls = [pub for pub in xmls_to_process if not pub.publication_filepath.name.startswith("bioc_")]
    pdfs_to_process = [pub for pub in controller.needs_transformation if pub.document_type == "PDF"]
    logging.info(f"Gathered {len(xmls_to_process)} .XML files to parse into JSON format.")
    logging.info(f"Gathered {len(pdfs_to_process)} .PDF files to parse into JSON format.")

    # Pre-transformation checks (tier, MinerU version, remote VLM settings, GPU availability). MinerU is an optional
    # extra, so it is only required when there are PDFs to convert.
    prepare_bulk_transformation(mineru_tier=mineru_tier, needs_mineru=bool(pdfs_to_process))

    ElsevierXmlTransformer(publication_list=elsevier_xmls, max_workers=xml_workers).transform_all()
    BioCXmlTransformer(publication_list=bioc_xmls, max_workers=xml_workers).transform_all()
    MinerUPdfTransformer(
        publication_list=pdfs_to_process,
        mineru_tier=mineru_tier,
        batch_size=mineru_batch_size,
    ).transform_all()

    # Build report if required.
    if generate_report:
        build_conversion_report(
            newly_converted=controller.needs_transformation,
            pre_cached=controller.needs_processing + controller.completed,
        )

    all_pubs = controller.needs_transformation + controller.needs_processing + controller.completed
    all_pubs = finalise_transformation(all_pubs)

    if cleanup_intermediates:
        cleanup_intermediate_files(all_pubs)
    return all_pubs

def standardise_text(
    publications: list[Publication],
    keep_figures: bool = False,
    keep_tables: bool = False,
    keep_inline_latex: bool = True,
    keep_display_latex: bool = False,
    keep_references: bool = False,
    keep_boilerplate: bool = False,
    normalise_imrad: bool = True,
    max_workers: int = 4,
) -> list[Publication]:
    """
    Clean and standardise JSON content-list files into final Markdown outputs.

    Reads each publication's content_json_filepath, applies content filters
    (figures, tables, LaTeX, references), optionally enforces IMRAD section
    structure via an Ollama LLM, and writes the result to the corpus results
    folder. Publications without a content_json_filepath are skipped.

    Requires a running Ollama instance when normalise_imrad=True. The
    function raises at the start if the endpoint is unreachable.

    Parameters
    ----------
    publications : list[Publication]
        Output of transform_text(). Publications without content_json_filepath
        set are silently skipped.
    keep_figures : bool, default False
        When False, image and chart blocks are replaced with a placeholder.
    keep_tables : bool, default False
        When False, table blocks are replaced with a placeholder.
    keep_inline_latex : bool, default True
        When False, inline equations (LaTeX spans inside sentences, headings, lists and algorithms) are replaced
        with a placeholder. Kept by default because inline LaTeX often carries units, symbols or statistics.
    keep_display_latex : bool, default False
        When False, display (standalone) equations are replaced with a placeholder.
    keep_references : bool, default False
        When False, reference lists are replaced with a placeholder. Text outside the reference list is never removed.
    keep_boilerplate : bool, default False
        When False, page headers, footers, page numbers, page footnotes, margin text and tables of contents are
        removed. For PMC BioC XML, footnotes and published peer-review history are removed; Elsevier XML contains
        none of these.
    normalise_imrad : bool, default True
        When True, attempt to trim each paper to its core text (Introduction to the end of the Discussion) and
        rename its section headings to Introduction / Methods / Results / Discussion, using regex matching with an
        LLM fallback. Best effort: a section neither can find is logged and left as-is. When False, headings are
        kept as extracted.
    max_workers : int, default 4
        Number of publications standardised concurrently. Mostly useful when the LLM fallback is in use, since
        Ollama can serve several requests at once. Set to 1 for strictly sequential processing.

    Returns
    -------
    list[Publication]
        All input publications that had a content_json_filepath. Successfully
        standardised publications have final_md_filepath set; others have it as None.
    """

    from biomarkit.config import get_corpus
    from biomarkit.standardisation.generics import prepare_standardisation
    from biomarkit.standardisation.text_cleaning.cleaner import Cleaner

    # The LLM is only used for IMRAD restructuring, so only check the endpoint when that is on.
    if normalise_imrad and not prepare_standardisation():
        raise RuntimeError(
            "Ollama endpoint is not reachable or the configured model is not installed. "
            "The LLM is required for normalise_imrad=True to classify headings that "
            "regex cannot match. Start Ollama and ensure the model is pulled, or set "
            "normalise_imrad=False to skip IMRAD normalisation."
        )

    logging.debug("Preflight checks passed. Proceeding with standardisation.")

    # Get only publications that have not already been standardised (final_md_filepath is not set in the cache).
    publications = [p for p in publications if p.content_json_filepath is not None and p.final_md_filepath is None]
    logging.debug(f"standardise_text: {len(publications)} publications have raw markdown files.")

    # Build the custom instructions for the Cleaner class.
    context = {"keep_figures": keep_figures,
               "keep_tables": keep_tables,
               "keep_inline_latex": keep_inline_latex,
               "keep_display_latex": keep_display_latex,
               "keep_references": keep_references,
               "keep_boilerplate": keep_boilerplate,
               "normalise_imrad": normalise_imrad}

    # Instantiate the Cleaner class and clean the publications according to the params defined by the user.
    cleaner = Cleaner(
        publications=publications,
        cache=get_corpus().db,
        context=context,
        max_workers=max_workers,
    )
    cleaner.clean_all()

    standardised = [p for p in publications if p.final_md_filepath is not None]
    logging.info(f"standardise_text: {len(standardised)}/{len(publications)} publications standardised.")
    return publications


if __name__ == "__main__":
    # Usage: uv run python -m biomarkit.pipeline <corpus> [options]  (same as the `biomarkit` command)
    from biomarkit.cli import main
    main()
