from __future__ import annotations
from typing import Dict
import logging
from time import perf_counter
from pathlib import Path
from config import SCOPUS_INPUT_CSV, DB_CACHE_FILE
from text_extraction.filter import filter_scopus_csv as ftr
from text_extraction.utils.generics import setup_logging, setup_run, clean_publications
from text_extraction.controller.controller import Controller
from text_extraction.apis.router import ApiRouter
from text_extraction.visualisation.text_extraction_report import build_text_extraction_report
from text_extraction.basemodels.publication import Publication
from text_extraction.visualisation.text_extraction_report import build_text_extraction_report

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
        CORPORA_DIR, DOWNLOAD_DIR, RAW_MARKDOWN_DIR, FINAL_MARKDOWN_DIR, REPORT_DIR, LOG_DIR,
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
        DOWNLOAD_DIR.name, RAW_MARKDOWN_DIR.name, FINAL_MARKDOWN_DIR.name, REPORT_DIR.name, LOG_DIR.name,
    ):
        (corpus_dir / subdir_name).mkdir(parents=True, exist_ok=True)

    logging.info(
        f"Corpus '{name}' ready at {corpus_dir}. Place your Scopus export there as "
        f"'{SCOPUS_INPUT_CSV.name}' and set CORPUS_NAME = \"{name}\" in config.py to use it."
    )
    return corpus_dir

def extract_text(check_opensource: bool = True, scopus_report: bool = False) -> list[Publication]:
    """
    Main function for downloading all academic publications from the results of a scopus query. Returns a list of
    standardized 'publication' objects. Each object contains metadata for the publication, as well as the filepath
    at which the full-text PDF/XML is located. Set scopus_report=True to include the Scopus input summary charts
    in the text-extraction report.
    """

    # Start timing the whole function.
    function_start = perf_counter()

    # Setup & check any downloaded publications are stored in a cache.
    setup_logging(level=logging.INFO)
    setup_run()
    clean_publications()

    # Load input query and filter.
    raw_df = ftr.load_scopus_csv(SCOPUS_INPUT_CSV)

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
    if all_publications:
        build_text_extraction_report(
            df=df, downloaded_pubs=all_publications, cached_pubs=cached_pubs,
            scopus_report=scopus_report,
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
    skip_conversion: bool = False,
    mineru_endpoint: str = "local",
) -> list[Publication]:
    """
    Converts downloaded publications (PDF/XML) into raw markdown files. Set
    mineru_endpoint="vllm" to delegate MinerU PDF inference to the remote vLLM server
    configured via MINERU_VLLM_ENDPOINT and MINERU_API_KEY in secrets.env (both are
    checked before the run starts); the default "local" runs MinerU on the local GPU.
    """

    from text_transformation.utils.generics import prepare_bulk_transformation, finalise_transformation
    from text_transformation.controller.controller import Controller
    from text_transformation.converters.elsevier_xml_to_md import ElsevierXmlConverter
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfConverter
    from text_transformation.visualisation.conversion_report import build_conversion_report

    # Pre-transformation checks (affirms vLLM secrets are filled when mineru_endpoint="vllm").
    prepare_bulk_transformation(mineru_endpoint=mineru_endpoint)

    # Send publications to text transformation controller to categorize them for processing based on cached state,
    controller = Controller(publication_list=publications)
    controller.prepare_publications()

    if skip_conversion:
        logging.info(
            f"skip_conversion=True — skipping {len(controller.needs_conversion)} unconverted publication(s), "
            f"proceeding with {len(controller.needs_processing) + len(controller.fully_processed)} cached."
        )
    else:
        # Build raw Markdown files for publications that require conversion.
        xmls_to_process = [pub for pub in controller.needs_conversion if pub.document_type == "XML"]
        pdfs_to_process = [pub for pub in controller.needs_conversion if pub.document_type == "PDF"]
        logging.info(f"Gathered {len(xmls_to_process)} .XML files to parse into markdown format.")
        logging.info(f"Gathered {len(pdfs_to_process)} .PDF files to parse into markdown format.")

        # Convert to raw md.
        ElsevierXmlConverter(publication_list=xmls_to_process).convert_all()
        MinerUPdfConverter(publication_list=pdfs_to_process, mineru_endpoint=mineru_endpoint).convert_all()

    # Build conversion report.
    build_conversion_report(
        newly_converted=[] if skip_conversion else controller.needs_conversion,
        pre_cached=controller.needs_processing + controller.fully_processed,
    )

    # Validate and return publications for downstream standardisation.
    if skip_conversion:
        all_pubs = controller.needs_processing + controller.fully_processed
    else:
        all_pubs = controller.needs_conversion + controller.needs_processing + controller.fully_processed
    return finalise_transformation(all_pubs)

def standardise_text(publications: list[Publication],
                     keep_figures: bool = False,
                     keep_tables: bool = False,
                     keep_latex: bool = False,
                     keep_references: bool = False,
                     force_imrad_structure = True) -> list[Publication]:
    """
    Cleans and standardizes raw markdown file outputs from text_transformation() into a final standardised markdown
    format that can be customised by the user through the context parameter. Returns the publications that were
    successfully standardized (final_md_filepath set in the cache).
    """

    from standardisation.generics import prepare_standardisation
    from standardisation.text_cleaning.cleaner import Cleaner

    # Pre-flight: check the LLM fallback endpoint. The run continues without it.
    llm_available = prepare_standardisation()

    # Raise a runtime error to inform the user that the ollama endpoint is not accessible.
    if not llm_available:
        raise RuntimeError("LLM fallback endpoint is not available. Cannot proceed.")

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
        cache=DB_CACHE_FILE,
        context=context
    )
    cleaner.clean_all()

    # Get total number of cleaned publications.
    standardised = [p for p in publications if p.final_md_filepath is not None]
    logging.info(f"standardise_text: {len(standardised)}/{len(publications)} publications standardised.")
    return standardised


if __name__ == "__main__":

    setup_logging(level=logging.INFO)
    logging.info("Starting full pipeline.")

    publications = extract_text(check_opensource=True, scopus_report=False)

    logging.info("Download stage completed - Starting markdown conversion.")
    transform_start = perf_counter()
    publications = transform_text(publications, skip_conversion=False)
    transform_seconds = perf_counter() - transform_start
    logging.info("transform_text() complete in %.2fs. Starting standardise_text().", transform_seconds)

    logging.info("Conversion of first paper may take longer due to model weight download.")
    standardise_start = perf_counter()
    standardise_text(publications, keep_latex=False, keep_tables=False, force_imrad_structure=True)
    standardise_seconds = perf_counter() - standardise_start
    logging.info("standardise_text() complete in %.2fs.", standardise_seconds)

    logging.info(
        "Pipeline complete — transform: %.2fs | standardise: %.2fs | total conversion: %.2fs",
        transform_seconds, standardise_seconds, transform_seconds + standardise_seconds,
    )