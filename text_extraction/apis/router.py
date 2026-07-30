from .clients.opensource import OpenSourceClient
from collections import defaultdict
from text_extraction.apis.abc.publisher_api import PublisherApi
from text_extraction.apis.map import api_clients
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import MAX_THREADS
from typing import List, Dict
from text_extraction.basemodels.publication import Publication
from text_extraction.utils.generics import validate_pdf_file, validate_xml_file


class ApiRouter:
    """
    This class handles and manages API calls to a number of different clients. It will carry out a number of rolls and
    spawn API clients as parallel processes.

    INPUT - The API Router accepts a list of publication objects without publication_filepath attributes.
    OUTPUT - The API routers final output is a list of publication objects; publication objects will have the
    attribute is_cached set to True if a successful full-text download was achieved.

    Roles
    1) Attempts to download all publications via open-source routes (preprint servers + Unpaywall).
    1) Shunts failed publications to publisher-specific API clients. Spawns the relevant API clients as "nodes" in
     parallel. Each node corresponds to a single API client, which in turn handles its own api logic.
    3) After all nodes have returned a list of publication objects with publication_filepaths, passes back the final
    list.

    Init values.
    self.publication list: A list of publication objects that the router will sort and attempt to download.
    self.try_opensource: (Default True). A boolean flag that if True, will initially attempt to download all papers via
    open-source routes before attempting to download papers via more specific APIs.
    self.finished_publications: (Default = []). This list stores publication objects that have been successfully
    downloaded by the router and have been added to the cache.
    self.unfinished_publications: (Default = []). This list stores publication objects that have not been successfully
    downloaded and cached.
    """

    # Attribute types.
    publication_list: List[Publication]
    finished_publications: List[Publication]
    unfinished_publications: List[Publication]

    def __init__(self, publication_list: List[Publication]):
        self.publication_list = publication_list
        self.finished_publications = []
        self.unfinished_publications = []
        self.try_opensource: bool = True

    # Statics.
    @staticmethod
    def _sort_publications(publications: List[Publication]) -> Dict[str, List[Publication]]:
        """
        Static method that will sort a list of publication objects into a dictionary of lists, sorted by value of
        publication.publisher.

        The publisher will match the name of the client to invoke and allows for easy routing/spawning of API client
        nodes.

        Parameters
        ----------
        publications: List[Publication]

        Returns
        -------
        Dict[str, List[Publication]]
        """
        logging.info("Grouping publications by publisher.")
        sorted_pubs: Dict[str, List[Publication]] = defaultdict(list)

        for pub in publications:
            sorted_pubs[pub.publisher].append(pub)

        return dict(sorted_pubs)

    @staticmethod
    def _map_to_nodes(pub_dict: Dict[str, List[Publication]], client_mapper: Dict[str, PublisherApi]) -> list:
        """
        Maps a dictionary of publication objects sorted by publisher to a class mapper containing the API clients for
        each available publisher. Once mapped, the function will instantiate the classes and return them as a list of
        instantiated objects.

        Parameters
        ----------
        pub_dict : Dict[str, List[Publication]]
        client_map: Dict[str, PublisherApi]

        Returns
        -------
        List[PublicationApi]
        """

        client_map = [client_mapper[key](pub_list) for key, pub_list in pub_dict.items() if key in client_mapper]

        logging.info("Client map contains:")
        for client in client_map:
            logging.info(f"\t{client.name}: Will attempt to download {len(client.publication_list)} publications.")

        return client_map

    @staticmethod
    def _run_publisher(publisher: PublisherApi) -> List[Publication] or [] :
        """Helper function to handle downloading all publications for a single client."""
        try:
            n_pubs = len(publisher.publication_list)
            logging.info(f"Starting client for {publisher.name}: Will attempt download for {n_pubs}.")
            publisher.download_all_papers()
            logging.info(f"Finished attempting downloads for {publisher.name}.")
            return publisher.publication_list

        except Exception as e:
            logging.error(f"Error in client {publisher.name}: {e}")
            return publisher.publication_list

    @staticmethod
    def _download_in_parallel(client_list: List[PublisherApi], max_threads: int) -> Dict[str, List[Publication]]:
        """
        Attempts to download all papers for each PublisherAPI object inside client_list in parallel, with a max number
        of threads. Each node will handle its own logging. Returns a list of lists. Each list contains the publications
        for a single publisher.

        Parameters
        ----------
        client_list: List[PublisherApi]
        max_threads: int

        Returns
        -------
        List[List[Publication]]
        """
        logging.info(f"Launching {len(client_list)} clients with up to {max_threads} parallel threads...")
        results = {}

        with ThreadPoolExecutor(max_workers=max_threads) as executor:
            futures = {executor.submit(ApiRouter._run_publisher, client): client for client in client_list}

            for future in as_completed(futures):
                pub = futures[future]

                try:
                    result = future.result()
                    results[pub.name] = result
                    logging.info(f"{pub.name} completed with {len(result)} publications.")

                except Exception as e:
                    logging.error(f"Unhandled exception in {pub.name}: {e}")
                    results[pub.name] = []


        logging.info("All publisher clients finished.")
        return results

    # Methods.
    def throw_at_opensource(self):
        """
        If self.try_opensource is true, this function will attempt to download all papers in self.publication_list
        using the open-source API client (arXiv/bioRxiv/ChemRxiv direct routes + Unpaywall fallback).

        Returns a list of publication objects that were successfully downloaded using open-source routes. Failed
        publications are not included.

        Returns
        -------
        List[Publication]
        """

        if self.try_opensource:

            logging.info("Attempting to spawn open-source API client node.")
            os_client = OpenSourceClient(publication_list=self.publication_list)
            logging.info("Spawned open-source API client node.")
            logging.info(f"Attempting to download {len(self.publication_list)} papers via open-source routes.")

            if len(self.publication_list) == 0:
                logging.error("Open-source client download failed because there are no papers in self.publication_list.")

            # Attempt to download all the papers, papers are added to the cache once downloaded.
            os_client.download_all_papers()
            logging.info("Open-source client node signalled all download attempts completed.")

            self.finished_publications =  [pub for pub in os_client.publication_list if pub.is_cached]
            logging.debug(f"Added {len(self.finished_publications)} publications to self.finished_publications.")

    def disperse_to_nodes(self) -> Dict[str, List[Publication]]:
        """
        Sorts publications without file paths into groups based on their publisher. Then passes each list of
        publications to their relative API to attempt to download. Returns a list of lists, each list contains
        all publications that download was attempted for. If the download was successful for the Publication object,
        its filepath will be updated.

        Returns
        -------
        Dict[str, List[Publication]]
        """

        # Sort all publications without a filepath into a dictionary of lists.
        logging.info("Separating publications that could not be downloaded via open-source routes.")
        pubs_for_attempt = [pub for pub in self.publication_list if pub.publication_filepath is None]

        # Sort unfinished publications and route to relative API clients for attempting download.
        logging.info(f"Router will try to download {len(pubs_for_attempt)} using specific publisher nodes.")
        pubs_by_publisher = self._sort_publications(pubs_for_attempt)
        logging.info(f"Router found {len(pubs_by_publisher)} publisher groups.")

        # Add publications that do not have a valid API to self.unfinished publications.
        for publisher, pub_list in pubs_by_publisher.items():
            if publisher not in api_clients.keys():
                self.unfinished_publications.extend(pub_list)

        # Attempt to download from specific APIs:
        logging.info(f"Spawning client nodes and appending relative publications to publisher.publication_list...")
        node_list = self._map_to_nodes(pub_dict=pubs_by_publisher, client_mapper=api_clients)
        logging.info(f"Successfully generated list of {len(node_list)} client nodes.")
        logging.info("Attempting downloads in parallel...")
        results = self._download_in_parallel(client_list=node_list, max_threads=MAX_THREADS)
        logging.info(f"Parallel downloads finished. Finalising...")

        return results

    def finalise_publication_list(self, download_results: Dict[str, List[Publication]]) -> List[Publication]:
        """
        Flattens results and builds a final list of publication objects to pass back as the final output.
        Will perform some assert statements to make sure that all Publication objects passed as input are passed back
        after routing to individual APIs.

        Returns
        -------
        List[Publication]
        """

        # Flatten publications into a list and extend self.finished_publications.
        logging.debug(f"Flattening {len(download_results)} publications.")
        self.finished_publications += [pub for pubs in download_results.values() for pub in pubs]

        # Assert that finished and unfinished publications both == size of the whole input.
        assert len(self.finished_publications) + len(self.unfinished_publications) == len(self.publication_list)
        all_publications = self.finished_publications + self.unfinished_publications
        return all_publications
