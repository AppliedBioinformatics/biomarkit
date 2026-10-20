from pathlib import Path
from typing import Optional

from biomarkit.config import TMP_DIR
from biomarkit.text_download.apis.abc.playwright_publisher_api import PlaywrightPublisherApi
from biomarkit.text_download.basemodels.publication import Publication


class MdpiClient(PlaywrightPublisherApi):
    """
    MDPI has tight bot security. A web-scraper is needed to visit the page and trigger
    the download of the PDF. This class uses Playwright (via PlaywrightPublisherApi) to
    avoid bot-detection issues. Download links are obtained via Unpaywall.
    """

    def __init__(self, publication_list: list):
        super().__init__(name="mdpi", publication_list=publication_list, timeout=1)

    def attempt_fallback(self, doi: str, filepath: str) -> bool:
        """
        Fallback for when Unpaywall has no PDF link: resolves the DOI to the MDPI article page in the
        browser, then downloads <article URL>/pdf. Done in the browser (not requests) because MDPI's
        bot protection rejects plain HTTP requests.
        """
        try:
            self.logger.info(f"Resolving article page for {doi} via https://doi.org/{doi}")
            self.page.goto(f"https://doi.org/{doi}", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            self.logger.error(f"Could not resolve article page for {doi}: {e}")
            return False

        article_url = self.page.url.split("?")[0].split("#")[0].rstrip("/")
        if "mdpi.com" not in article_url:
            self.logger.error(f"DOI {doi} did not resolve to an MDPI article page (got {article_url}).")
            return False
        return self._attempt_download(doi=doi, url=f"{article_url}/pdf", filepath=filepath)

    def download_paper(self, doi: str) -> Optional[Path]:
        download_url = self._get_pdf_url(doi=doi)
        filepath = self._build_download_filepath()

        success = False
        if download_url:
            self.logger.info(f"Open access URL found for DOI: {doi}. Attempting to download...")
            success = self._attempt_download(doi=doi, url=download_url, filepath=filepath)
        else:
            self.logger.info(f"No open access PDF URL found for DOI: {doi}.")

        if not success:
            self.logger.info("Attempting fallback via the MDPI article page.")
            success = self.attempt_fallback(doi=doi, filepath=filepath)

        if not success:
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