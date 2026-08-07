from __future__ import annotations
import logging
from time import perf_counter
from pathlib import Path

from text_download.basemodels.publication import Publication

# High-level functions.
def create_corpus(name: str) -> Path:
    """
    Creates the folder structure for a new corpus at corpora/<name>.

    Builds the empty corpus subfolders (manuscripts, markdowns, results, reports, logs).
    The Scopus export must then be placed inside the corpus folder as scopus.csv, and
    CORPUS_NAME in config.py set to <name>, before running the pipeline. Safe to call
    on an existing corpus — existing contents are left untouched.

    Parameters
    ----------
    name : str - Folder name for the new corpus.

    Returns
    -------
    Path - Path to the corpus folder.
    """
    from config import (
        CORPORA_DIR, DOWNLOAD_DIR, JSON_STRUCT_DIR, FINAL_MARKDOWN_DIR, REPORT_DIR, LOG_DIR, SCOPUS_INPUT_CSV_NAME
    )

    name = name.strip()
    if not name or set('\\/:*?"<>|') & set(name):
        raise ValueError(
            f"Invalid corpus name: {name!r}. Use a plain folder name without path separators."
        )

    corpus_dir = CORPORA_DIR / name
    if corpus_dir.exists():
        logging.warning(f"Corpus '{name}' already exists at {corpus_dir} — leaving existing contents untouched.")

    for subdir_name in (
            DOWNLOAD_DIR.name, JSON_STRUCT_DIR.name, FINAL_MARKDOWN_DIR.name, REPORT_DIR.name, LOG_DIR.name,
    ):
        (corpus_dir / subdir_name).mkdir(parents=True, exist_ok=True)

    logging.info(
        f"Corpus '{name}' ready at {corpus_dir}. Place your Scopus export there as "
        f"'{SCOPUS_INPUT_CSV_NAME.name}' and set CORPUS_NAME = \"{name}\" in config.py to use it."
    )
    return corpus_dir

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

    from config import SCOPUS_INPUT_CSV_NAME
    from text_download.filter import filter_scopus_csv as ftr
    from text_download.utils.generics import setup_logging, setup_run, clean_publications
    from text_download.controller.controller import Controller
    from text_download.apis.router import ApiRouter
    from text_download.visualisation.text_extraction_report import build_text_download_report

    # Start timing the whole function.
    function_start = perf_counter()

    # Setup & check any downloaded publications are stored in a cache.
    setup_logging(level=logging.INFO)
    setup_run()
    clean_publications()

    # Load input query and filter.
    raw_df = ftr.load_scopus_csv(SCOPUS_INPUT_CSV_NAME)

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
    mineru_backend: str = "local-gpu",
    mineru_batch_size: int | None = None,
    generate_report: bool = False
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
    mineru_backend : {"local-gpu", "local-cpu", "vllm"}, default "local-gpu"
        "local-gpu" runs MinerU on the local CUDA GPU (requires PyTorch + CUDA).
        "local-cpu" runs MinerU on CPU only — slower but no GPU required.
        "vllm" delegates PDF inference to the remote vLLM server configured via
        MINERU_VLLM_ENDPOINT and MINERU_API_KEY in secrets.env (both are validated
        before the run starts).
t    mineru_batch_size : int | None, default None (inherits MinerUPdfTransformer default of 25)
        Number of PDFs to send to MinerU per invocation. None sends all pending
        PDFs in a single call. Set a positive integer to process in sequential
        chunks — each completed chunk is cached before the next begins.

    Returns
    -------
    list[Publication]
        All input publications, including those already cached from a previous run.
        Each object has content_json_filepath set if conversion succeeded.
    """

    from text_transformation.utils.generics import prepare_bulk_transformation, finalise_transformation
    from text_transformation.controller.controller import Controller
    from text_transformation.converters.elsevier2json import ElsevierXmlTransformer
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    from text_transformation.visualisation.conversion_report import build_conversion_report

    # Pre-transformation checks (affirms vLLM secrets are filled when mineru_backend="vllm").
    prepare_bulk_transformation(mineru_backend=mineru_backend)

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
        mineru_backend=mineru_backend,
        batch_size=mineru_batch_size,
    ).transform_all()

    # Build report if required.
    if generate_report:
        build_conversion_report(
            newly_converted=controller.needs_transformation,
            pre_cached=controller.needs_processing + controller.completed,
        )

    all_pubs = controller.needs_transformation + controller.needs_processing + controller.completed
    return finalise_transformation(all_pubs)

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

    from config import DB_CACHE_FILE_NAME
    from standardisation.generics import prepare_standardisation
    from standardisation.text_cleaning.cleaner import Cleaner

    llm_available = prepare_standardisation()
 
    if not llm_available and force_imrad_structure:
        raise RuntimeError(
            "Ollama endpoint is not reachable or the configured model is not installed. "
            "The LLM is required for force_imrad_structure=True to classify headings that "
            "regex cannot match. Start Ollama and ensure the model is pulled, or set "
            "force_imrad_structure=False to use regex-only heading detection."
        )

    logging.info("Preflight checks passed. Proceeding with standardisation.")

    # Get only publications that have not already been standardised (final_md_filepath is not set in the cache).
    publications = [p for p in publications if p.content_json_filepath is not None]
    logging.info(f"standardise_text: {len(publications)} publications have raw markdown files.")

    # Build the custom instructions for the Cleaner class.
    context = {"keep_figures": keep_figures,
               "keep_tables": keep_tables,
               "keep_latex": keep_latex,
               "keep_references": keep_references,
               "force_imrad_structure": force_imrad_structure}

    # Instantiate the Cleaner class and clean the publications according to the params defined by the user.
    cleaner = Cleaner(
        publications=publications,
        cache=DB_CACHE_FILE_NAME,
        context=context
    )
    cleaner.clean_all()

    standardised = [p for p in publications if p.final_md_filepath is not None]
    logging.info(f"standardise_text: {len(standardised)}/{len(publications)} publications standardised.")
    return publications


if __name__ == "__main__":
    from text_download.utils.generics import setup_logging

    # Setup.
    setup_logging(level=logging.INFO)
    logging.info("Complete a full new corpus conversion.")

    # Download.
    publications = download_corpus(check_opensource=True, generate_report=False)
    logging.info("Corpus download completed.")

    # Convert.
    publications = transform_text(publications, mineru_backend="local-gpu", mineru_batch_size=10)
    logging.info("Corpus transformation completed.")

    # Standardise.
    logging.info("Conversion of first paper may take longer due to model weight download.")
    standardise_text(publications,
                     keep_latex=True,
                     keep_tables=True,
                     keep_figures=False,
                     keep_references=False,
                     force_imrad_structure=True)

    logging.info("Corpus standardisation completed.")