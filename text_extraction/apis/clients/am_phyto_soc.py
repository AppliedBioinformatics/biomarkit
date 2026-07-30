from pathlib import Path
from typing import Optional

from config import TMP_DIR
from text_extraction.apis.abc.publisher_api import PublisherApi
from text_extraction.basemodels.publication import Publication


class AmPhytoSocClient(PublisherApi):
    """
    Client for downloading papers from the American Phytopathological Society (APS).
    APS hosts journals on Atypon/Literatum at apsjournals.apsnet.org. Open-access PDFs
    can be downloaded directly via the URL pattern:

        https://apsjournals.apsnet.org/doi/pdf/{doi}

    No API key or Playwright is required — direct HTTP with standard headers works.
    The download logic is inherited from the base PublisherApi class.
    """

    def __init__(self, publication_list: list):
        super().__init__(name="american_phytopathological_society", publication_list=publication_list)
        self.timeout = 10

    def _test_url(self) -> bool:
        """APS root URL returns 403 but individual PDF URLs work fine. Skip the health check."""
        return True

    def download_paper(self, doi: str) -> Optional[Path]:
        url = f"https://apsjournals.apsnet.org/doi/pdf/{doi}"
        filepath = self._build_download_filepath()
        success = self._attempt_download(doi=doi, url=url, filepath=filepath)

        if not success:
            self.logger.info(f"Download attempt failed for {doi} from client: {self.name}")
            return None

        self.logger.info(f"Paper downloaded for DOI: {doi} at filepath: {filepath}.")
        return filepath


if __name__ == "__main__":
    doi_list = [
        "10.1094/PHYTO-10-21-0430-PER",
        "10.1094/PBIOMES-01-23-0001-R",
    ]
    pubs = [Publication(doi=i, year=2020, title="Publication for testing", publisher="american_phytopathological_society") for i in doi_list]
    client = AmPhytoSocClient(publication_list=pubs)
    client.download_dir = TMP_DIR
    client.download_all_papers()