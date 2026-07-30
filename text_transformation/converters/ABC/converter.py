import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from config import DB_CACHE_FILE, RAW_MARKDOWN_DIR
from text_extraction.basemodels.publication import Publication
from text_extraction.database.database import update_raw_md_filepath


class Converter(ABC):
    """
    Abstract base class for all text-transformation converters.

    Subclasses implement convert() with their specific conversion logic.
    convert_all() handles the iteration, error handling, Publication update,
    and cache write — shared across all converters.

    Attributes
    ----------
    publication_list : List[Publication] - Publications to convert.
    output_dir : Path - Directory where raw markdown files are written.
    cache : Path - Path to the SQLite cache database.
    """

    def __init__(self, publication_list: List[Publication]):
        self.publication_list = publication_list
        self.output_dir = RAW_MARKDOWN_DIR
        self.cache = DB_CACHE_FILE

    @abstractmethod
    def convert(self, pub: Publication) -> Path | None:
        """
        Converter-specific conversion logic for a single publication.

        Parameters
        ----------
        pub : Publication - The publication to convert.

        Returns
        -------
        Path - Path to the generated raw markdown file, or None if conversion failed.
        """
        pass

    def _build_output_path(self, pub: Publication) -> Path:
        """
        Derives the output markdown filepath from the publication's source filename.
        Output convention: output_dir/<stem>/<stem>.md

        Parameters
        ----------
        pub : Publication - Must have publication_filepath set.

        Returns
        -------
        Path - Target path for the raw markdown file.
        """
        if pub.publication_filepath is None:
            raise ValueError(f"Cannot build output path for {pub.doi}: publication_filepath is not set.")
        stem = pub.publication_filepath.stem
        return self.output_dir / stem / f"{stem}.md"

    def _cache_result(self, pub: Publication) -> None:
        """
        Writes the raw_md_filepath back to the cache row for the given publication.

        Parameters
        ----------
        pub : Publication - Must have raw_md_filepath set before calling.
        """
        update_raw_md_filepath(
            doi=pub.doi,
            raw_md_filepath=str(pub.raw_md_filepath),
            db_path=self.cache,
        )
        logging.info(f"Cache updated with raw_md_filepath for {pub.doi}.")

    def convert_all(self) -> None:
        """
        Iterates self.publication_list, calls convert() on each publication,
        updates pub.raw_md_filepath on success, and writes the result to the cache.
        Failed conversions are logged as warnings and skipped.

        Returns
        -------
        None
        """
        total = len(self.publication_list)
        logging.info(f"{self.__class__.__name__} starting conversion of {total} publication(s).")

        passed, failed = 0, 0
        for i, pub in enumerate(self.publication_list, start=1):
            logging.info(f"Converting publication {i}/{total}: {pub.doi}.")
            try:
                result = self.convert(pub)
                if result is None:
                    logging.warning(f"Conversion returned None for {pub.doi} — skipping.")
                    failed += 1
                    continue
                pub.raw_md_filepath = result
                self._cache_result(pub)
                passed += 1

            except Exception as e:
                logging.warning(f"Conversion failed for {pub.doi}: {e} — skipping.")
                failed += 1

        logging.info(
            f"{self.__class__.__name__} finished — {passed} succeeded, {failed} failed."
        )