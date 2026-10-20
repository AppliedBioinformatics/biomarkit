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

    All other pipeline functions (download_corpus, transform_text, standardise_text) read and
    write the corpus loaded here, so call this first.

    Parameters
    ----------
    corpus : str | Path
        A corpus name (resolved to <BIOMARKIT_DIR>/corpora/<name>) or a path to a corpus folder.
    scopus_file : str | Path | None, default None
        Scopus export CSV. Required to build a new corpus; copied into an existing corpus only
        if it has no scopus.csv yet.
    build : bool | None, default None
        What to do if the corpus folder doesn't exist. None asks for confirmation when running
        interactively (terminal or notebook) and raises otherwise. True builds without asking
        (use this in batch jobs). False never builds and raises FileNotFoundError.

    Returns
    -------
    list[Publication]
        One Publication per DOI found in the cache, with metadata from the Scopus CSV and
        filepaths populated wherever they exist in the cache. Empty for a new corpus.
    """
    from biomarkit.config import set_active_corpus
    from biomarkit.text_download.filter import filter_scopus_csv as ftr
    from biomarkit.text_download.database.database import get_all_cached_dois, get_row_for_doi, _to_absolute
    from biomarkit.text_download.utils.generics import resolve_corpus_path, build_corpus

    corpus_dir = resolve_corpus_path(corpus)

    if not corpus_dir.exists():
        if build is False:
            raise FileNotFoundError(f"Corpus not found at {corpus_dir}.")
        if scopus_file is None:
            raise ValueError(f"Corpus not found at {corpus_dir}. Pass scopus_file=... to build a new corpus there.")
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

    raw_df = ftr.load_scopus_csv(paths.scopus_csv)
    df = ftr.remove_imperfect_rows(df=raw_df)
    df = ftr.synchronise_publishers(df=df)
    df = df[df["DOI"].isin(cached_dois)]

    publications = ftr.build_publication_objects(df=df)

    for pub in publications:
        row = get_row_for_doi(pub.doi, db_path=paths.db)
        if row is None:
            continue
        if row.get("publication_filepath"):
            pub.publication_filepath = _to_absolute(row["publication_filepath"], paths.db)
        if row.get("content_json_filepath"):
            pub.content_json_filepath = _to_absolute(row["content_json_filepath"], paths.db)
        if row.get("final_md_filepath"):
            pub.final_md_filepath = _to_absolute(row["final_md_filepath"], paths.db)

    return publications

def download_corpus(check_opensource: bool = True, generate_report: bool = False) -> list[Publication]:
    """
    Download full-text PDFs and XMLs for all publications in the active corpus's Scopus CSV.

    Each DOI is routed through a two-stage process: open-access routes (arXiv, bioRxiv,
    ChemRxiv, Unpaywall) are tried first when check_opensource=True, then publisher APIs
    (Elsevier, Wiley, Springer, MDPI, Frontiers, etc.) handle the remainder. Previously
    downloaded publications are loaded from the SQLite cache and download for these is not
    attempted. An HTML report is always written to the corpus reports folder on completion.

    Parameters
    ----------
    check_opensource : bool, default True
        When True, attempt open-access routes before falling back to publisher APIs.
        Set to False to skip directly to publisher specific APIs.

    Returns
    -------
    list[Publication]
        All publications from the Scopus CSV, including those loaded from cache.
        Each object carries DOI, title, publisher, year, document type, and the
        filepath of the downloaded PDF or XML (None if download failed).
    """

    from biomarkit.config import get_corpus
    from biomarkit.text_download.filter import filter_scopus_csv as ftr
    from biomarkit.text_download.utils.generics import setup_logging, setup_run, clean_publications
    from biomarkit.text_download.controller.controller import Controller
    from biomarkit.text_download.apis.router import ApiRouter
    from biomarkit.text_download.visualisation.text_extraction_report import build_text_download_report

    # Start timing the whole function.
    function_start = perf_counter()

    # Setup & check any downloaded publications are stored in a cache.
    setup_logging(level=logging.INFO)
    setup_run()
    clean_publications()

    # Load input query and filter.
    raw_df = ftr.load_scopus_csv(get_corpus().scopus_csv)

    # Filter + Synchronize. (Can add more steps here)
    df = ftr.remove_imperfect_rows(df=raw_df)
    df = ftr.synchronise_publishers(df=df)

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
) -> list[Publication]:
    """
    Convert downloaded PDFs and XMLs into structured JSON content-list files.

    Elsevier XMLs are parsed directly; all other PDFs are processed via MinerU.
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

    Returns
    -------
    list[Publication]
        All input publications, including those already cached from a previous run.
        Each object has content_json_filepath set if conversion succeeded.
    """

    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation, finalise_transformation, cleanup_intermediate_files
    from biomarkit.text_transformation.controller.controller import Controller
    from biomarkit.text_transformation.converters.elsevier2json import ElsevierXmlTransformer
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    from biomarkit.text_transformation.visualisation.conversion_report import build_conversion_report

    # Pre-transformation checks (tier, MinerU version, remote VLM settings, GPU availability).
    prepare_bulk_transformation(mineru_tier=mineru_tier)

    # Send publications to text transformation controller to categorize them for processing based on cached state.
    controller = Controller(publication_list=publications)
    controller.prepare_publications()

    # Build JSON structure files for each publication if they have not already been generated by a previous run.
    xmls_to_process = [pub for pub in controller.needs_transformation if pub.document_type == "XML"]
    pdfs_to_process = [pub for pub in controller.needs_transformation if pub.document_type == "PDF"]
    logging.info(f"Gathered {len(xmls_to_process)} .XML files to parse into JSON format.")
    logging.info(f"Gathered {len(pdfs_to_process)} .PDF files to parse into JSON format.")

    ElsevierXmlTransformer(publication_list=xmls_to_process).transform_all()
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
    keep_latex: bool = False,
    keep_references: bool = False,
    force_imrad_structure: bool = True,
) -> list[Publication]:
    """
    Clean and standardise JSON content-list files into final Markdown outputs.

    Reads each publication's content_json_filepath, applies content filters
    (figures, tables, LaTeX, references), optionally enforces IMRAD section
    structure via an Ollama LLM, and writes the result to the corpus results
    folder. Publications without a content_json_filepath are skipped.

    Requires a running Ollama instance when force_imrad_structure=True. The
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
    keep_latex : bool, default False
        When False, inline and block equations are replaced with a placeholder.
    keep_references : bool, default False
        When False, an attempt is made to remove the references section from the paper.
    force_imrad_structure : bool, default True
        When True, section headings are normalised to Introduction / Methods /
        Results / Discussion using regex matching with an LLM fallback. Paper boilerplate sections are parsed to a
        classifier to decide whether to remove each section.

    Returns
    -------
    list[Publication]
        All input publications that had a content_json_filepath. Successfully
        standardised publications have final_md_filepath set; others have it as None.
    """

    from biomarkit.config import get_corpus
    from biomarkit.standardisation.generics import prepare_standardisation
    from biomarkit.standardisation.text_cleaning.cleaner import Cleaner

    llm_available = prepare_standardisation()
 
    if not llm_available and force_imrad_structure:
        raise RuntimeError(
            "Ollama endpoint is not reachable or the configured model is not installed. "
            "The LLM is required for force_imrad_structure=True to classify headings that "
            "regex cannot match. Start Ollama and ensure the model is pulled, or set "
            "force_imrad_structure=False to use regex-only heading detection."
        )

    logging.debug("Preflight checks passed. Proceeding with standardisation.")

    # Get only publications that have not already been standardised (final_md_filepath is not set in the cache).
    publications = [p for p in publications if p.content_json_filepath is not None and p.final_md_filepath is None]
    logging.debug(f"standardise_text: {len(publications)} publications have raw markdown files.")

    # Build the custom instructions for the Cleaner class.
    context = {"keep_figures": keep_figures,
               "keep_tables": keep_tables,
               "keep_latex": keep_latex,
               "keep_references": keep_references,
               "force_imrad_structure": force_imrad_structure}

    # Instantiate the Cleaner class and clean the publications according to the params defined by the user.
    cleaner = Cleaner(
        publications=publications,
        cache=get_corpus().db,
        context=context
    )
    cleaner.clean_all()

    standardised = [p for p in publications if p.final_md_filepath is not None]
    logging.info(f"standardise_text: {len(standardised)}/{len(publications)} publications standardised.")
    return publications


if __name__ == "__main__":
    # Usage: uv run python -m biomarkit.pipeline [corpus name or path]
    import sys
    from biomarkit.text_download.utils.generics import setup_logging

    corpus = r"C:\Users\jackb\OneDrive\Documents\GitHub\biomarkit\biomarkit\corpora\barley_water_logging"

    # Setup.
    setup_logging(level=logging.INFO)
    logging.info("Complete a full new corpus conversion.")
    load_corpus(corpus, build=False)

    # Download.
    publications = download_corpus(check_opensource=True, generate_report=True)
    logging.info("Corpus download completed.")

    # Convert.
    publications = transform_text(publications,
                                  mineru_tier="standard",
                                  mineru_batch_size=25,
                                  cleanup_intermediates=True)

    logging.debug("Corpus transformation completed.")

    # Standardise.
    logging.debug("Conversion of first paper may take longer due to model weight download.")
    standardise_text(publications,
                     keep_latex=True,
                     keep_tables=True,
                     keep_figures=False,
                     keep_references=False,
                     force_imrad_structure=True)

    logging.info("Corpus standardisation completed.")