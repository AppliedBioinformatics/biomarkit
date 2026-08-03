import logging
from pathlib import Path
from typing import List

import config
from text_extraction.basemodels.publication import Publication
from text_extraction.database.database import create_database, get_row_for_doi


class Controller:
    """
    Receives a list of Publication objects and cross-references each against the cache database.
    Sorts publications into three lists based on how many filepath columns are populated:

    - needs_conversion  : publication_filepath only — content JSON not yet generated.
    - needs_processing  : publication_filepath + content_json_filepath — final markdown not yet generated.
    - fully_processed   : all three filepaths set — no further action required.
    """

    def __init__(self, publication_list: List[Publication]):
        logging.info("Attempting to instantiate text_transformation Controller.")

        self.publications = publication_list
        self.cache = config.DB_CACHE_FILE

        self.needs_conversion: List[Publication] = []
        self.needs_processing: List[Publication] = []
        self.fully_processed: List[Publication] = []

        self._check_cache()
        logging.info("Successfully instantiated text_transformation Controller.")

    def _check_cache(self) -> None:
        """Create or load the database cache file."""
        if self.cache.exists():
            logging.info(f"Loading existing cache from {self.cache}")
        else:
            logging.info(f"Cache not found at {self.cache}, creating a new one...")
            create_database(self.cache)

    def _filter_uncached_publications(self) -> None:
        """
        Removes publications with is_cached == False from self.publications before any
        cache cross-referencing begins. Discarded publications are logged as warnings.
        """
        logging.info("Filtering out uncached publications.")
        cached, discarded = [], []
        for pub in self.publications:
            (cached if pub.is_cached else discarded).append(pub)

        if discarded:
            for pub in discarded:
                logging.debug(f"Publication {pub.doi} is not cached — discarding.")
            logging.info(f"{len(discarded)} uncached publication(s) discarded (Publications that were not downloaded).")

        self.publications = cached
        logging.info(f"{len(self.publications)} cached publication(s) retained for processing.")

    def _update_publications_cache_state(self) -> None:
        """
        Populates all three filepath fields on each Publication from the cache row.
        Logs a warning for any publication whose cache row has no publication_filepath
        (this should not occur under normal operation).
        """
        logging.info("Cross-referencing publication objects with cache.")
        for pub in self.publications:
            row = get_row_for_doi(pub.doi, db_path=self.cache)
            if row is None:
                continue  # Already caught by _validate_all_publications_cached.
            if not row.get("publication_filepath"):
                logging.warning(
                    f"Publication {pub.doi} is in the cache but has no publication_filepath — skipping."
                )
                continue

            pub.publication_filepath = Path(row["publication_filepath"])
            pub.content_json_filepath = Path(row["content_json_filepath"]) if row.get("content_json_filepath") else None
            pub.final_md_filepath = Path(row["final_md_filepath"]) if row.get("final_md_filepath") else None

        logging.info("Finished updating publication filepath states from cache.")

    def _update_document_types(self) -> None:
        """
        Sets document_type to XML for any publication whose raw_filepath has a .xml extension.
        Only runs after _update_publications_cache_state has populated the filepath fields.
        """
        for pub in self.publications:
            if pub.publication_filepath and pub.publication_filepath.suffix.lower() == ".xml":
                pub.document_type = "XML"
                logging.debug(f"Publication {pub.doi} identified as XML document type.")

    def _sort_publications(self) -> None:
        """
        Sorts publications into three lists based on how many filepath columns are set.
        """
        for pub in self.publications:
            if not pub.is_cached:
                logging.warning(
                    f"Publication {pub.doi} has no publication_filepath after cache update — skipping sort."
                )
                continue
            if pub.is_processed:
                self.fully_processed.append(pub)
            elif pub.is_converted:
                self.needs_processing.append(pub)
            else:
                self.needs_conversion.append(pub)

        logging.info(
            f"Sort complete — needs_conversion: {len(self.needs_conversion)}, "
            f"needs_processing: {len(self.needs_processing)}, "
            f"fully_processed: {len(self.fully_processed)}."
        )

    def prepare_publications(self) -> None:
        """
        Public entry point. Validates all publications are cached, updates their filepath
        state from the cache, then sorts them into the three processing lists.
        """
        self._update_publications_cache_state()
        self._filter_uncached_publications()
        self._update_document_types()
        self._sort_publications()