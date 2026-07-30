from pathlib import Path
from typing import Optional

from config import TMP_DIR
from text_extraction.apis.abc.publisher_api import PublisherApi
from text_extraction.basemodels.publication import Publication


class CopernicusClient(PublisherApi):
    """
    Client for downloading papers from Copernicus Publications (copernicus.org).
    All Copernicus journals are fully open access. PDFs are served directly via a
    predictable URL derived from the DOI suffix:

        DOI:  10.5194/{journal}-{vol}-{start_page}-{year}
        URL:  https://{journal}.copernicus.org/articles/{vol}/{start_page}/{year}/{suffix}.pdf

    No API key or Playwright is required. _download_pdf_if_valid() is used rather than
    _attempt_download() because Copernicus returns HTTP 200 HTML error pages for missing
    papers, so the PDF magic-byte check is needed to confirm a real download.
    """

    def __init__(self, publication_list: list):
        super().__init__(name="copernicus", publication_list=publication_list)
        self.timeout = 10

    def _test_url(self) -> bool:
        # copernicus.org root redirects and fails the standard health check; individual
        # article URLs work fine, so skip it.
        return True

    def _build_pdf_url(self, doi: str) -> Optional[str]:
        """
        Derives the direct PDF URL from a Copernicus DOI.

        Expected DOI format:  10.5194/{journal}-{vol}-{start_page}-{year}
        Returns None if the suffix does not match that pattern.
        """
        if "/" not in doi:
            return None
        suffix = doi.split("/", 1)[1]          # e.g. "gmd-13-4713-2020"
        parts = suffix.split("-")
        if len(parts) < 4 or not parts[1].isdigit() or not parts[2].isdigit() or not parts[3].isdigit():
            self.logger.warning(f"Unexpected Copernicus DOI format: {doi}")
            return None
        journal, vol, start_page, year = parts[0], parts[1], parts[2], parts[3]
        return f"https://{journal}.copernicus.org/articles/{vol}/{start_page}/{year}/{suffix}.pdf"

    def download_paper(self, doi: str) -> Optional[Path]:
        url = self._build_pdf_url(doi)
        if url is None:
            return None

        filepath = self._build_download_filepath()
        success = self._download_pdf_if_valid(url=url, filepath=filepath)

        if not success:
            self.logger.info(f"Download attempt failed for {doi} from client: {self.name}")
            return None

        self.logger.info(f"Paper downloaded for DOI: {doi} at filepath: {filepath}.")
        return filepath


if __name__ == "__main__":
    doi_list = [
        "10.5194/gmd-13-4713-2020",
        "10.5194/hess-29-261-2025",
        "10.5194/acp-24-2287-2024",
    ]
    pubs = [Publication(doi=i, year=2020, title="Publication for testing", publisher="copernicus") for i in doi_list]
    client = CopernicusClient(publication_list=pubs)
    client.download_dir = TMP_DIR
    client.download_all_papers()