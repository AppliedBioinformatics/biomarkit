import logging

import config
from typing import List, Dict
from collections import defaultdict
from text_download.basemodels.publication import Publication
from text_download.database.database import create_database, get_row_for_doi

class Controller:
    """
    The controller receives a list of Publication objects built using an initial Scopus query. It will do the following
    jobs:

    ### 1 - Passes uncached papers to the open-source download stage. ###
    1.A - Checks each Publication object DOI to see if it is already cached.
    1.B - Updates the Publication.is_cached if above is True.
    1.C - Sorts publications based on is_cached result.
    2.A - Passes a Dictionary of lists to the API router in format "publisher": [Publications].

    ### 3 - Waits for response from API.
    3.A - Receives a list of cached publication objects from the API router.
    3.B - Adds the cached publications to self.cached_publications and removes from uncached.

    ### 4 - Final checks and data analysis before submitting to next pipeline step.
    4.A - Checks to make sure that all received publications have been cached and each filepath exists.
    4.B - Checks to see if all files have been downloaded and build metrics for which ones are not.
    4.C - Passes a final list of cached publication objects up the pipeline.
    """

    def __init__(self, publication_list: List[Publication]):

        logging.info("Attempting to instantiate Controller.")

        self.publications = publication_list
        self.cache = config.DB_CACHE_FILE_NAME
        self.cached_publications = []
        self.uncached_publications = []

        # Check cache exists, if not, create it.
        self._check_cache()
        logging.info("Successfully instantiated Controller.")

    # Funcs for 1.
    def _check_cache(self):
        """Create or load the database cache file."""
        if self.cache.exists():
            logging.info(f"Loading existing cache from {self.cache}")

        else:
            logging.info(f"Cache not found at {self.cache}, creating a new one...")
            create_database(self.cache)


    def _check_publications(self):
        """
        Checks to make sure all publications in self.publications are valid before caching checks can begin.

        Returns
        -------
        bool: True if all publications are valid, False otherwise.
        """

        logging.info("Controller is validating all publications.")

        assert len(self.publications) > 0, "Controller.publications is empty!"
        for pub in self.publications:
            assert type(pub) is Publication

        logging.info("All publications are valid.")


    def _update_publications_cache_state(self) -> None:
        """
        Checks each publication in self.publication to see if it has been previously downloaded. Performs a checks.
        to see if the doi is already cached. If true, it will attempt to set publication.publication_filepath to that
        row.

        If the doi exists in the database but the filepath does not point to an existing file on the system, a
        pydantic validation error will be raised through the Publication object. The filepath existence is handled by
        the pydantic.filepath type so no need to worry about non-existent filepaths here.

        Returns
        -------
        None

        """

        logging.info("Controller is cross-referencing publication objects with Cache.")

        for pub in self.publications:

            # 1 - Check to see if the DOI is in the database. Only add the filepath if it actually exists.
            cached_row = get_row_for_doi(pub.doi, db_path=self.cache)
            if cached_row:
                pub.publication_filepath = cached_row["publication_filepath"]

        logging.info("Controller finished checking cache for existing publication filepaths.")

    def prepare_publications_for_router(self) -> dict:
        """
        This function is a wrapper function for the above methods. The function carries out Role 1 of the controller (
        specified in the class docstring). The function returns a dictionary of uncached publications ready for
        forwarding to the api router.

        Returns
        -------
        dict
        """
        self._check_publications()
        self._update_publications_cache_state()

        # Sort results.
        logging.info("Sorting publications based on cached status.")
        self.cached_publications = [pub for pub in self.publications if pub.is_cached]
        self.uncached_publications = [pub for pub in self.publications if not pub.is_cached]

        logging.info(f"Identified {len(self.uncached_publications)} uncached publications.")
        logging.info(f"Identified {len(self.cached_publications)} cached publications.")
        logging.info("Publications are now checked and filepaths are validated.")

        return self.uncached_publications, self.cached_publications



