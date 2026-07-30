from pathlib import Path
from typing import Optional

import requests
from requests.exceptions import RequestException

from config import TMP_DIR
from text_extraction.apis.abc.playwright_publisher_api import PlaywrightPublisherApi
from text_extraction.basemodels.publication import Publication


class FrontiersClient(PlaywrightPublisherApi):
    """
    """

    def __init__(self, publication_list: list):
        super().__init__(name="frontiers", publication_list=publication_list, timeout=5)

    def attempt_fallback(self, doi: str, filepath: str) -> bool:
        """
        Attempts to download the PDF using the generic Frontiers open-access URL pattern.
        """
        generic_url = f"http://journal.frontiersin.org/article/{doi}/pdf"

        try:
            self.logger.info(f"Attempting fallback download from generic URL: {generic_url}")
            response = requests.get(generic_url, stream=True, timeout=self.timeout)
            response.raise_for_status()

            with open(filepath, 'wb') as pdf_file:
                for chunk in response.iter_content(chunk_size=8192):
                    pdf_file.write(chunk)

            self.logger.info(f"Successfully downloaded PDF (Fallback Attempt) to {filepath}")
            return True

        except RequestException as fallback_e:
            self.logger.error(f"Fallback download also failed for {doi}. Error: {fallback_e}")
            return False

    def download_paper(self, doi: str) -> Optional[Path]:
        download_url = self._get_pdf_url(doi=doi)
        filepath = self._build_download_filepath()

        if not download_url:
            self.logger.info(f"No open access URL found for DOI: {doi}.")
            self.logger.info("Attempting fallback method with generalised url.")
            success = self.attempt_fallback(doi=doi, filepath=filepath)
        else:
            self.logger.info(f"Open access URL found for DOI: {doi}. Attempting to download...")
            success = self._attempt_download(doi=doi, url=download_url, filepath=filepath)

        if not success:
            return None

        self.logger.info(f"Paper downloaded for DOI: {doi} at filepath: {filepath}.")
        return filepath


if __name__ == "__main__":
    doi_list = [
        "10.3389/fpls.2018.01012",
        "10.3389/fpls.2018.00923",
        "10.1016/j.cell.2025.05.028",
        "10.3389/fpls.2018.01727",
        "10.3389/fgene.2020.00799",
    ]
    pubs = [Publication(doi=i, year=2020, title="Publication for testing", publisher="frontiers") for i in doi_list]
    client = FrontiersClient(publication_list=pubs)
    client.download_dir = TMP_DIR
    client.download_all_papers()