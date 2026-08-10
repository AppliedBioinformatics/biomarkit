import logging

from config import TMP_DIR
from text_download.basemodels.publication import Publication
from pathlib import Path
from text_download.apis.abc.publisher_api import PublisherApi

class SpringerClient(PublisherApi):
    """
    Springer Nature has its own API Python package that is used to download, but this doesn't actually allow for
    full-text downloads. For open access articles, this turned out to be pretty simple. The DOI can be downloaded from
    springer sites with url in format: url = "https://link.springer.com/content/pdf/" + doi + ".pdf". The rest of the
    download logic is inherited from the base PublisherApi class.
    """

    # === Inherits from PublicationApi Class ===
    def __init__(self, publication_list: list):
        super().__init__(name="springer", publication_list=publication_list)
        self.timeout = 10
        # Springer's bot detection rejects the browser-spoofing default_headers;
        # a plain requests call (no custom headers) returns the PDF correctly.
        self.request_headers = {}

    # === These methods are inherited from PublicationApi and should be overwritten. ===
    def download_paper(self, doi: str) -> Path or None:

        # Build the url link and attempt to download.
        url = "https://link.springer.com/content/pdf/" + doi + ".pdf"
        filepath = self._build_download_filepath()
        status_code = self._attempt_download(doi=doi, url=url, filepath=filepath)

        if not status_code:
            self.logger.debug(f"Download attempt failed for {doi} from client: {self.name}")
            return None

        self.logger.debug(f"Paper downloaded for DOI: {doi} at filepath: {filepath}.")
        return filepath


if __name__ == "__main__":

    # Some real Springer papers.
    doi_list = [
        #"10.1186/s12885-023-11574-y",
        #"10.1038/s41467-024-45158-6",
        #"10.1007/s42452-025-07743-2",
        #"10.1007/s44155-025-00318-x",
        #"10.1186/s40594-022-00385-5",
        "10.1186/s12870-024-04817-y"
    ]

    pubs = [Publication(doi=i, year=2020, title="Publication for testing", publisher="springer") for i in doi_list]
    client = SpringerClient(publication_list=pubs)
    client.download_dir = TMP_DIR
    response = client.download_all_papers()
