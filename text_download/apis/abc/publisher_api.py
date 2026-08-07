import time
from abc import ABC, abstractmethod
from typing import List
from text_download.basemodels.publication import Publication
from text_download.database.database import insert_row
from text_download.apis.strings import default_headers
from text_download.utils.generics import progress_split_bar
from config import USER_EMAIL, API_KEY_TO_NAME, API_URL_TO_NAME, DOWNLOAD_DIR, DB_CACHE_FILE_NAME, LOG_DIR
from pathlib import Path
import random
import logging
import requests
from tqdm import tqdm

class PublisherApi(ABC):
    """
    Abstract base class for all publication API clients for downloading papers. All publisher specific clients
    should be built on top of this class to enable common functionality and to ensure that inputs/outputs remain the
    same, whilst keeping api limits etc. specific to individual clients.

    Each API client will be instantiated by the API router module that will sort publications for download. The input
    for every API client will be a list of Publication objects that the client will attempt to download using
    its specific API request functions.
    """

    # Attribute Types.
    name: str
    publication_list: List[Publication]
    timeout: int

    def __init__(self, name, publication_list, timeout: int = 10):
        self.name = name
        self.publication_list = publication_list
        self.email = USER_EMAIL
        self.download_dir = DOWNLOAD_DIR
        self.api_url = API_URL_TO_NAME[self.name]
        self.api_key = API_KEY_TO_NAME[self.name]
        self.timeout = timeout
        self.request_headers = default_headers
        self.logger = self._setup_logger()

        if not self._test_url():
            raise ConnectionError(f"Could not connect to {self.api_url} for api client node: {self.name}.")

        self.logger.info(f"Spawned node for {self.name} Client.")

    # Functions where logic is shared across all APIs.
    def _setup_logger(self) -> logging.Logger:
        """
        Configures instance-specific logging to a file. This means that logs are separated by instance, and makes
        debugging particular instances easier. All logs are saved at LOG_DIR location.

        Returns
        -------
        logging.Logger
        """
        logger = logging.getLogger(f"PublisherApi.{self.name}")
        logger.setLevel(logging.INFO)

        # Ensure that multiple instances don't duplicate log handlers.
        if not logger.handlers:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_file = LOG_DIR / f"{self.name}_client.log"
            handler = logging.FileHandler(log_file)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        # Prevent log messages leaking up to the root logger (console).
        logger.propagate = False
        return logger

    def _test_url(self) -> bool:
        """
        Test function that runs during instantiation to ensure that the Client can obtain a response from the
        url end point

        Returns
        -------
        bool: True if the url returns an OK status code, False otherwise.
        """

        try:
            response = requests.get(self.api_url)
            response.raise_for_status()
            return True

        except requests.exceptions.RequestException as e:
            logging.warning(f"API error: {e} - API end-point {self.name} not reachable.")
            return False

    def _build_download_filepath(self, filetype: str = "pdf", source: str = None) -> Path:
        """
        Builds the filepath that a single Publication download can be saved at. Uses self.name parameter so that
        downloads can be traced back to their relative clients. file extension is passed using the filetype parameter.
        The default is "pdf". to change, use "xml" or "html" etc. Clients with multiple download routes can pass
        source to override the self.name prefix, so files can be traced back to the route that produced them.

        Returns
        -------
        Path
        """
        random_id = ''.join(random.choices('0123456789', k=10))
        filepath = self.download_dir / f"{source or self.name}_{random_id}.{filetype}"
        return filepath

    def _attempt_download(self, doi:str, url: str, filepath:Path) -> bool:
        """
        Attempts to download from a URL and handles errors accordingly. This function handles cases where the API
        response contains an open-access url for a publication, but the download fails. This can be due to a multitude of
        reasons such as bot detection. This function should contain standardised logic that will be checked across all
        api clients. Not all Specific clients will use this function, APIs such as Wiley utilise pre-built packages
        that this logic internally.
        """

        try:
            self._download_paper_from_url(url=url, filepath=filepath)
            return True

        # Bot detected.
        except requests.exceptions.HTTPError as e:
            self.logger.info(f"Cannot download paper from URL for DOI {doi} at url: {url} - "
                            f"probably due to bot detection.")
            return False

        # Host name mismatch.
        except requests.exceptions.SSLError as e:
            self.logger.info(f"Cannot download paper for DOI: {doi} at url: {url} - "
                         f"probably due to host-name mismatch.")
            return False

        # Timeout.
        except requests.exceptions.ReadTimeout as e:
            self.logger.info(f"Cannot download paper for DOI: {doi} at url: {url} - "
                             f"probably due to server-end timeout.")
            return False

        # General connection error.
        except requests.exceptions.ConnectionError as e:
            self.logger.info(f"Cannot download paper for DOI: {doi} at url: {url} - "
                             f"probably due to connection error.")
            return False

        # Excess redirects.
        except requests.exceptions.TooManyRedirects as e:
            self.logger.info(f"Cannot download paper for DOI: {doi} at url: {url} - "
                             f"probably due to too many redirects.")
            return False

    def _download_paper_from_url(self, url: str, filepath: Path) -> None:
        """
        Attempts to download a paper from a URL link and save to a file at the filepath parameter.
        Parameters
        ----------
        url: str
        filepath: Path

        Returns
        -------
        None
        """
        response = requests.get(url, headers=self.request_headers, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()

        with open(filepath, "wb") as f:
            f.write(response.content)

        self.logger.info(f"Finished writing bytes to {filepath}.")

        return None

    def _download_pdf_if_valid(self, url: str, filepath: Path, headers: dict = None, timeout: int = None) -> bool:
        """
        Downloads a URL and saves it to filepath, but only when the response body is a real PDF. Failure pages
        (bot challenges, "PDF unavailable" notices) often come back as HTTP 200 HTML, so the status code alone
        is not a success signal. headers and timeout default to the client's own when not passed. Returns True
        only when a PDF was written to filepath.
        """
        headers = headers if headers is not None else self.request_headers
        timeout = timeout if timeout is not None else self.timeout

        try:
            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            response.raise_for_status()

        except requests.exceptions.RequestException as e:
            self.logger.info(f"Could not download PDF from url: {url} - {e}")
            return False

        if not response.content.startswith(b"%PDF"):
            self.logger.info(f"Response from {url} is not a PDF - skipping write.")
            return False

        with open(filepath, "wb") as f:
            f.write(response.content)

        self.logger.info(f"Finished writing bytes to {filepath}.")
        return True

    def _cache_successful_download(self, pub: Publication) -> None:
        """
        Adds a single publication to the cache.

        Returns
        -------
        None
        """

        if pub.publication_filepath:
            self.logger.info("Adding publication to cache.")
            insert_row(doi=pub.doi, downloaded_from=self.name,
                       publication_filepath=str(pub.publication_filepath), db_path=DB_CACHE_FILE_NAME)

        else:
            self.logger.error("Publication object has no existing filepath attached. Why has it been passed for caching?")
            raise ValueError("Tried to cache a Publication object with no existing filepath.")

    #---------------------------------
    # Client specific logic goes here.
    #---------------------------------
    @abstractmethod
    def download_paper(self, doi: str) -> Path or None:
        """
        This function should contain all API-specific logic required to gracefully download a single paper using the
        DOI passed as an argument. If the download is successful, the function should return a Path object to the
        download. If the download fails for any reason, the function should return None.

        Parameters
        ----------
        doi: str

        Returns
        -------
        Path or None
        """
        pass

    def download_all_papers(self) -> None:
        """
        Main function for attempting to download all papers in self.publication_list. The function should iterate over
        each publication in self.publication_list and check to see if a filepath or None is returned -
        (see self.download_paper()). The function should also handle caching on successful downloads.

        Returns
        -------
        None
        """
        total = len(self.publication_list)
        self.logger.info(f"Attempting to download {total} papers from {self.name}.")

        success, failed = 0, 0
        with tqdm(self.publication_list, desc=self.name, unit="paper", leave=True, dynamic_ncols=True) as bar:
            for p in bar:
                time.sleep(self.timeout)
                self.logger.debug(f"Attempting to download: {p.doi}.")
                filepath = self.download_paper(doi=p.doi)

                if filepath:
                    p.publication_filepath = filepath
                    self.logger.debug(f"Updated related Publication object 'publication_filepath' attribute.")
                    self._cache_successful_download(pub=p)
                    success += 1
                else:
                    failed += 1

                bar.set_postfix_str(progress_split_bar(success, failed, total))

        self.logger.debug(f"{self.name}.download_all_papers() completed — {success}/{total} downloaded.")




