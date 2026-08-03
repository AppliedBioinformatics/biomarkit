from pathlib import Path
from typing import Optional

from config import TMP_DIR
from text_download.apis.abc.playwright_publisher_api import PlaywrightPublisherApi
from text_download.basemodels.publication import Publication


class MdpiClient(PlaywrightPublisherApi):
    """
    MDPI has tight bot security. A web-scraper is needed to visit the page and trigger
    the download of the PDF. This class uses Playwright (via PlaywrightPublisherApi) to
    avoid bot-detection issues. Download links are obtained via Unpaywall.
    """

    def __init__(self, publication_list: list):
        super().__init__(name="mdpi", publication_list=publication_list, timeout=1)

    def download_paper(self, doi: str) -> Optional[Path]:
        download_url = self._get_pdf_url(doi=doi)

        if not download_url:
            self.logger.info(f"No open access URL found for DOI: {doi}.")
            return None

        self.logger.info(f"Open access URL found for DOI: {doi}. Attempting to download...")
        filepath = self._build_download_filepath()

        if not self._attempt_download(doi=doi, url=download_url, filepath=filepath):
            return None

        self.logger.info(f"Paper downloaded for DOI: {doi} at filepath: {filepath}.")
        return filepath


if __name__ == "__main__":
    print("Attempting downloads:")
    doi_list = [
        "10.3390/plants14182820",
        "10.3390/genes16080907",
        "10.3390/agronomy15081889",
        "10.3390/foods14142462",
        "10.3390/plants14121877",
    ]
    pubs = [Publication(doi=i, year=2020, title="Publication for testing", publisher="mdpi") for i in doi_list]
    client = MdpiClient(publication_list=pubs)
    client.download_dir = TMP_DIR
    client.download_all_papers()