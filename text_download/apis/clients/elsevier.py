from text_download.basemodels.publication import Publication
from pathlib import Path
from text_download.apis.abc.publisher_api import PublisherApi
from config import API_KEY_TO_NAME, TMP_DIR
import time


class ElsevierClient(PublisherApi):
    """
    Class desc...
    """

    # === Inherits from PublicationApi Class ===
    def __init__(self, publication_list: list):
        super().__init__(name="elsevier", publication_list=publication_list)
        self.api_key = API_KEY_TO_NAME[self.name]
        self.timeout = 10
        self.request_headers = {"X-ELS-APIKey": self.api_key, "Accept": "application/xml"}

        for p in self.publication_list:
            p.document_type = "XML"

    # ===Client specific methods - not overwritten from PublisherApi. ===


    # === These methods are inherited from PublicationApi and should be overwritten. ===
    def download_paper(self, doi: str) -> Path or None:
        url = f"https://api.elsevier.com/content/article/doi/{doi}"
        filepath = self._build_download_filepath(filetype="xml")
        status_code = self._attempt_download(doi=doi, url=url, filepath=filepath)

        if not status_code:
            self.logger.info(f"Download attempt failed for {doi} from client: {self.name}")
            return None

        self.logger.info(f"Paper downloaded for DOI: {doi} at filepath: {filepath}.")
        self.logger.debug("ElsevierAPI.download_paper() completed.")
        return filepath

if __name__ == "__main__":

    # Some real Springer papers.
    doi_list = [
        "10.1016/j.resenv.2025.100216"
        "10.1016/j.eswa.2024.124167",
        "10.1016/j.comptc.2025.115470",
        "10.1016/j.susoc.2022.05.004",
        "10.1016/j.ijin.2022.08.005",
        "10.1016/j.comptc.2025.115464"
    ]

    pubs = [Publication(doi=i, year=2020, title="Publication for testing", publisher="elsevier") for i in doi_list]
    client = ElsevierClient(publication_list=pubs)
    client.download_dir = TMP_DIR
    client.download_all_papers()