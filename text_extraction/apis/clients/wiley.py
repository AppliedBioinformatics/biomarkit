from pathlib import Path
from text_extraction.apis.abc.publisher_api import PublisherApi
from wiley_tdm import TDMClient
from config import WILEY_TDM_TOKEN, TMP_DIR
from text_extraction.basemodels.publication import Publication
import logging
import shutil

class WileyClient(PublisherApi):
    """
    The Wiley publishing group are maintaining their own Python package for downloading PDF's via their API. This class
    uses this package (wiley-tdm) to handle paper downloads. Documentation for the package is available here:
    https://github.com/WileyLabs/tdm-client?tab=readme-ov-file#wiley-tdm-client. API limits at wiley allow for 60
    requests every 10 minutes, to prevent errors, self.timeout is set to 10 (seconds) for this client.
    """

    # === Inherits from PublicationApi Class ===
    def __init__(self, publication_list: list):
        super().__init__(name="wiley", publication_list=publication_list)
        self.timeout = 10

        # Add the official Wiley client.
        self.wiley_client=self.connect_wiley_tdm()

    # ===Client specific methods - not overwritten from PublisherApi. ===
    def connect_wiley_tdm(self) -> TDMClient:
        """
        Links the Wiley TDM client to the class. Function should be run on instantiation.

        Returns
        -------
        TDMClient
        """

        if not WILEY_TDM_TOKEN:
            raise ValueError("WILEY_TDM_TOKEN environment variable not set. Please update .env file with WILEY_TDM_TOKEN.")

        tdm=TDMClient(api_token=WILEY_TDM_TOKEN, download_dir=TMP_DIR)
        self.logger.info("Connected to Wiley via TDM.")

        return tdm

    def _test_url(self) -> bool:
        """Wiley does not have a URL that is testable as it requires a token. This method overwrites
        PublisherApi._test_url. to prevent a failure on instantiation."""
        return True

    def _move_file(self, current_path: Path) -> bool:
        """Because the Wiley API Python package does not allow for renaming files on download, files must be saved to
        the TMP_FOLDER location. Once they are downloaded, this function is used to move and rename the file to the
        correct location (DOWNLOAD_FOLDER)."""

        new_filepath = self._build_download_filepath()

        self.logger.debug(f"Moving Wiley paper from TMP: {current_path} to DOWNLOADS: {new_filepath}")
        shutil.move(str(current_path), str(new_filepath))
        self.logger.debug(f"Move completed.")

        return new_filepath

    # === These methods are inherited from PublicationApi and should be overwritten. ===
    def download_paper(self, doi: str) -> Path or None:
        self.logger.info(f"Attempting to download paper for doi: {doi} using Wiley API.")
        result = self.wiley_client.download_pdf(doi)

        if str(result.status) == "Success" and Path(result.path).exists():
            current_path = result.path
            filepath = self._move_file(current_path=current_path)
            self.logger.info(f"Downloaded Publication for DOI: {doi} to {filepath} from Wiley API.")
            return filepath

        else:
            self.logger.info(f"Unable to download Publication for DOI: {doi} using Wiley API.")
            return None

if __name__ == "__main__":

    # Some real Wiley papers.
    doi_list = [
        "10.1002/tpg2.20221",
        "10.1002/agt2.70216",
        "10.1002/ggn2.202500040",
        "10.1002/agj2.70233",
        "10.1002/jvc2.70233"
    ]

    pubs = [Publication(doi=i, year=2020, title="Publication for testing", publisher="wiley") for i in doi_list]
    client = WileyClient(publication_list=pubs)
    response = client.download_all_papers()