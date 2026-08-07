import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List

from tqdm import tqdm

from config import DB_CACHE_FILE_NAME, JSON_STRUCT_DIR
from text_download.basemodels.publication import Publication
from text_download.database.database import update_content_json_filepath
from text_download.utils.generics import progress_split_bar


class Transformer(ABC):
    """
    Abstract base class for all text-transformation Transformers.

    Subclasses implement transform2json() with their specific transformation logic.
    transform_all() handles the iteration, error handling, Publication update,
    and cache write — shared across all transformers.

    Attributes
    ----------
    publication_list : List[Publication] - Publications to transform.
    output_dir : Path - Directory where JSON structure files are written.
    cache : Path - Path to the SQLite cache database.
    """

    def __init__(self, publication_list: List[Publication]):
        self.publication_list = publication_list
        self.output_dir = JSON_STRUCT_DIR
        self.cache = DB_CACHE_FILE_NAME

    @abstractmethod
    def transform2json(self, pub: Publication) -> Path | None:
        """
        transformation logic for a single publication.

        Parameters
        ----------
        pub : Publication - The publication to transform.

        Returns
        -------
        Path - Path to the generated JSON structure file, or None if transformation failed.
        """
        pass

    def _build_output_path(self, pub: Publication) -> Path:
        """
        Derives the content_list_v2.json filepath from the publication's source filename.
        Output convention: output_dir/<stem>/auto/<stem>_content_list_v2.json

        Parameters
        ----------
        pub : Publication - Must have publication_filepath set.

        Returns
        -------
        Path - Target path for the content_list_v2.json file.
        """
        if pub.publication_filepath is None:
            raise ValueError(f"Cannot build output path for {pub.doi}: publication_filepath is not set.")
        stem = pub.publication_filepath.stem
        return self.output_dir / stem / "auto" / f"{stem}_content_list_v2.json"

    def _cache_result(self, pub: Publication) -> None:
        """
        Writes the content_json_filepath back to the cache row for the given publication.

        Parameters
        ----------
        pub : Publication - Must have content_json_filepath set before calling.
        """
        update_content_json_filepath(
            doi=pub.doi,
            content_json_filepath=str(pub.content_json_filepath),
            db_path=self.cache,
        )
        logging.debug(f"Cache updated with content_json_filepath for {pub.doi}.")

    def transform_all(self) -> None:
        """
        Iterates self.publication_list, calls transform() on each publication,
        updates pub.content_json_filepath on success, and writes the result to the cache.
        Failed transformations are logged as warnings and skipped.

        Returns
        -------
        None
        """
        total = len(self.publication_list)
        logging.info(f"{self.__class__.__name__} starting transformation of {total} publication(s).")

        passed, failed = 0, 0
        with tqdm(self.publication_list, desc=self.__class__.__name__, unit="pub",
                  leave=True, dynamic_ncols=True) as bar:
            for pub in bar:
                if pub.content_json_filepath is not None:
                    passed += 1
                    bar.set_postfix_str(progress_split_bar(passed, failed, total))
                    continue
                logging.debug(f"Transforming: {pub.doi}.")
                try:
                    result = self.transform2json(pub)
                    if result is None:
                        logging.warning(f"Transformation returned None for {pub.doi} — skipping.")
                        failed += 1
                        bar.set_postfix_str(progress_split_bar(passed, failed, total))
                        continue
                    pub.content_json_filepath = result
                    self._cache_result(pub)
                    passed += 1

                except Exception as e:
                    logging.warning(f"Transformation failed for {pub.doi}: {e} — skipping.")
                    failed += 1

                bar.set_postfix_str(progress_split_bar(passed, failed, total))

        logging.info(
            f"{self.__class__.__name__} finished — {passed} succeeded, {failed} failed."
        )