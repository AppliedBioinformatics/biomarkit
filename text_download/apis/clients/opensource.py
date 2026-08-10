import re
from ..abc.publisher_api import PublisherApi
from pathlib import Path
import requests


class OpenSourceClient(PublisherApi):
    """Open-source download client (formerly the Unpaywall client). The router runs this client over
    every publication before dispersing failures to publisher-specific API nodes.

    Routes are tried per DOI in this order, each only firing when its DOI pattern matches:
        1. arXiv     - direct PDF URL built from the DOI (10.48550/arXiv.<id>).
        2. bioRxiv   - direct content URL (DOI prefix 10.1101/, shared with medRxiv - both tried).
        3. ChemRxiv  - Cambridge Open Engage public JSON API (DOI contains "chemrxiv").
        4. Unpaywall - best open-access location lookup (https://unpaywall.org/products/api).

    All routes are keyless. A failed route falls through to the next one. Download filenames are
    prefixed with the route that produced them (e.g. arxiv_1234567890.pdf) so files can be traced
    back to their source.
    """

    # Preprint-server routes use their own timeout and headers. self.timeout stays at 1 because
    # the base class also uses it as the per-paper politeness sleep in download_all_papers().
    preprint_timeout = 60
    preprint_headers = {"User-Agent": "biomarkit/1.0"}

    chemrxiv_api_url = "https://www.cambridge.org/engage/coe/public-api/v1/items/doi"

    # === Inherits from PublicationApi Class ===
    def __init__(self, publication_list: list):
        super().__init__(name="opensource", publication_list=publication_list)
        self.timeout = 1
        # Same bot-detection issue as SpringerClient: the browser-spoofing default_headers
        # cause publisher sites (BioMedCentral, Springer, etc.) to return HTML instead of PDFs.
        self.request_headers = {}

    # ===Client specific methods - not overwritten from PublisherApi. ===
    @staticmethod
    def _extract_arxiv_id(doi: str) -> str or None:
        """
        Pulls the arXiv identifier out of a DataCite arXiv DOI, e.g. 10.48550/arXiv.2207.03928
        gives 2207.03928 (an optional version suffix is kept). Old-style pre-2007 identifiers
        (e.g. math/0211159) are not supported and return None, so those DOIs fall through to
        the next route.
        """
        head, found, tail = doi.lower().partition("arxiv.")
        if not found:
            return None

        match = re.match(r"\d{4}\.\d{4,5}(?:v\d+)?", tail)
        return match.group(0) if match else None

    def _try_arxiv(self, doi: str) -> Path or None:
        """
        Direct arXiv route. Builds the PDF URL straight from the arXiv ID embedded in the DOI -
        no landing-page scrape or API lookup needed. Returns the filepath on success, else None.
        """
        arxiv_id = self._extract_arxiv_id(doi)
        if not arxiv_id:
            return None

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        filepath = self._build_download_filepath(source="arxiv")
        self.logger.info(f"DOI {doi} matched the arXiv route. Trying {pdf_url}.")

        if self._download_pdf_if_valid(url=pdf_url, filepath=filepath,
                                       headers=self.preprint_headers, timeout=self.preprint_timeout):
            return filepath
        return None

    def _try_biorxiv(self, doi: str) -> Path or None:
        """
        Direct bioRxiv content-URL route. The 10.1101/ DOI prefix is shared with medRxiv, so both
        domains are tried. bioRxiv sits behind Cloudflare: blocked requests come back as HTML that
        fails the %PDF check, which is expected - the DOI then falls through to the next route.
        """
        if not doi.lower().startswith("10.1101/"):
            return None

        for source, domain in (("biorxiv", "www.biorxiv.org"), ("medrxiv", "www.medrxiv.org")):
            pdf_url = f"https://{domain}/content/{doi}.full.pdf"
            filepath = self._build_download_filepath(source=source)
            self.logger.info(f"DOI {doi} matched the bioRxiv route. Trying {pdf_url}.")

            if self._download_pdf_if_valid(url=pdf_url, filepath=filepath,
                                           headers=self.preprint_headers, timeout=self.preprint_timeout):
                return filepath
        return None

    def _get_chemrxiv_item(self, doi: str) -> dict or None:
        """
        Queries the Cambridge Open Engage item-by-DOI endpoint for a ChemRxiv DOI. Returns the
        item dict, or None on any non-200 response or unparsable payload (common for old items).
        """
        try:
            resp = requests.get(f"{self.chemrxiv_api_url}/{doi}",
                                timeout=self.preprint_timeout, headers=self.preprint_headers)
            resp.raise_for_status()
            payload = resp.json()

        except (requests.exceptions.RequestException, ValueError):
            return None

        if not isinstance(payload, dict):
            return None

        # Some responses wrap the item, others return it bare.
        if "item" in payload:
            return payload["item"]
        return payload

    @staticmethod
    def _pick_chemrxiv_asset_url(item: dict) -> str or None:
        """Extracts the PDF link from a ChemRxiv item, preferring the original upload."""
        asset = item.get("asset")
        if not isinstance(asset, dict):
            return None

        original = asset.get("original")
        if isinstance(original, dict) and original.get("url"):
            return original["url"]

        return asset.get("url")

    def _try_chemrxiv(self, doi: str) -> Path or None:
        """
        ChemRxiv route via the Cambridge Open Engage public JSON API. Returns the filepath on
        success, else None.
        """
        if "chemrxiv" not in doi.lower():
            return None

        # Legacy Figshare-style DOIs carry a .vN suffix the API rejects, so a stripped variant
        # is queried as a second attempt.
        candidate_dois = [doi]
        base, separator, version = doi.rpartition(".v")
        if separator and version.isdigit():
            candidate_dois.append(base)

        item = None
        for candidate in candidate_dois:
            item = self._get_chemrxiv_item(candidate)
            if item is not None:
                break

        if not item:
            self.logger.info(f"ChemRxiv API returned no item for DOI: {doi}.")
            return None

        pdf_url = self._pick_chemrxiv_asset_url(item)
        if not pdf_url:
            self.logger.info(f"ChemRxiv item for DOI: {doi} has no downloadable asset.")
            return None

        filepath = self._build_download_filepath(source="chemrxiv")
        self.logger.info(f"DOI {doi} matched the ChemRxiv route. Trying {pdf_url}.")

        if self._download_pdf_if_valid(url=pdf_url, filepath=filepath,
                                       headers=self.preprint_headers, timeout=self.preprint_timeout):
            return filepath
        return None

    def _get_pdf_url(self, doi: str) -> str or None:
        """
        Queries Unpaywall to get the best open access PDF URL to download for a DOI. Returns a string of the url
        if it exists, else returns None.

        Parameters
        ----------
        doi: str

        Returns
        -------
        str or None
        """
        api_url = f"{self.api_url}/{doi}?email={self.email}"

        try:
            resp = requests.get(api_url, timeout=self.timeout)
            resp.raise_for_status()
            data=resp.json()
            best = data.get("best_oa_location") or {}
            return best.get("url_for_pdf") or best.get("url")

        except AttributeError:
            self.logger.info(f"Unable to retrieve url for DOI: {doi} via the fallback lookup.")
            return None

        except requests.exceptions.RequestException as e:
            self.logger.info(f"Unable to retrieve url for DOI: {doi} via the fallback lookup. URL does not exist.")

    def _try_unpaywall(self, doi: str) -> Path or None:
        """
        Unpaywall fallback route - queries the Unpaywall API for the best open-access location and
        downloads from it. Returns the filepath on success, else None.
        """

        # Attempt to retrieve a download link.
        download_url = self._get_pdf_url(doi=doi)

        # If no download link, then quit early.
        if not download_url:
            self.logger.info(f"No open access URL found for DOI: {doi} via the fallback route.")
            return None

        self.logger.info(f"Open access URL found for DOI: {doi}. Attempting to download...")
        filepath = self._build_download_filepath(source="unpaywall")

        if not self._download_pdf_if_valid(url=download_url, filepath=filepath):
            return None

        self.logger.info(f"Paper downloaded for DOI: {doi} at filepath: {filepath}.")
        return filepath

    # === These methods are inherited from PublicationApi and should be overwritten. ===
    def download_paper(self, doi: str) -> Path or None:
        """
        Downloads a single paper. Tries the direct preprint-server routes first
        (arXiv -> bioRxiv -> ChemRxiv), then falls back to the Unpaywall API.
        """

        for route in (self._try_arxiv, self._try_biorxiv, self._try_chemrxiv, self._try_unpaywall):
            filepath = route(doi)

            if filepath:
                self.logger.debug("opensource.download_paper() completed.")
                return filepath

        return None
