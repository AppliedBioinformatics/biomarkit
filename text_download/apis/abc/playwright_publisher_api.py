import asyncio
import subprocess
from pathlib import Path
from typing import Optional

import requests
from playwright.sync_api import sync_playwright

from config import API_URL_TO_NAME
from text_download.apis.abc.publisher_api import PublisherApi


class PlaywrightPublisherApi(PublisherApi):
    """
    Intermediate base class for publisher API clients that use Playwright for browser-based
    PDF downloads. Sits between PublisherApi (the ABC) and concrete clients like MdpiClient
    and FrontiersClient.

    Provides shared Playwright lifecycle management (browser init, cleanup), Unpaywall-based
    PDF URL lookup, and browser-based download logic. Concrete subclasses must still implement
    `download_paper()`.
    """

    def __init__(self, name: str, publication_list: list, timeout: int = 10):
        super().__init__(name=name, publication_list=publication_list, timeout=timeout)
        self.api_url = API_URL_TO_NAME["unpaywall"]

        # Playwright state attributes.
        self._p = None
        self.browser = None
        self.context = None
        self.page = None
        self._initialized = False

    # --- Playwright clients don't need HTTP health checks ---
    def _test_url(self) -> bool:
        return True

    # --- Playwright lifecycle ---
    def _ensure_playwright_browser(self) -> None:
        """
        Checks that the Playwright Chromium executable exists and runs
        'playwright install chromium' automatically if it is missing.

        Raises
        ------
        RuntimeError
            If the install command exits non-zero.
        """
        with sync_playwright() as p:
            executable = Path(p.chromium.executable_path)

        if executable.exists():
            return

        self.logger.warning(
            f"Playwright Chromium executable not found at {executable}. "
            "Running 'playwright install chromium'..."
        )
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"'playwright install chromium' failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
        self.logger.info("Playwright Chromium installed successfully.")

    def _initialise_playwright(self) -> None:
        """Initialize Playwright browser in the current thread."""
        if self._initialized:
            return

        # Create event loop for this thread if needed.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                raise RuntimeError("Loop is closed")
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        self._ensure_playwright_browser()
        self.logger.info("Initializing Playwright browser for Client")
        self._p = sync_playwright().start()

        self.browser = self._p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )

        self.context = self.browser.new_context(
            accept_downloads=True,
            user_agent=self.request_headers.get("User-Agent"),
            locale="en-US",
            viewport={"width": 1920, "height": 1080},
        )

        self.context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )

        self.page = self.context.new_page()
        self.logger.info("Playwright browser initialized successfully")
        self._initialized = True

    def close(self) -> None:
        """Shut down the Playwright browser and process, reset state."""
        if self.browser:
            self.browser.close()
            self.browser = None
        if self._p:
            self._p.stop()
            self._p = None
        self.context = None
        self.page = None
        self._initialized = False

    # --- Unpaywall PDF URL lookup ---
    def _get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Queries Unpaywall to get the best open access PDF URL for a DOI.

        Parameters
        ----------
        doi : str

        Returns
        -------
        Optional[str]
            The PDF URL if found, otherwise None.
        """
        api_url = f"{self.api_url}/{doi}?email={self.email}"

        try:
            resp = requests.get(api_url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            best = data.get("best_oa_location") or {}
            return best.get("url_for_pdf") or best.get("url")

        except AttributeError:
            self.logger.info(f"Unable to retrieve url for DOI: {doi}.")
            return None

        except requests.exceptions.RequestException as e:
            self.logger.info(f"Unable to retrieve url for DOI: {doi}. URL does not exist.")
            return None

    # --- Browser-based download ---
    def _attempt_download(self, doi: str, url: str, filepath: str) -> bool:
        """
        Download a PDF by navigating the Playwright browser to the URL and
        capturing the triggered download.

        Parameters
        ----------
        doi : str
        url : str
        filepath : str

        Returns
        -------
        bool
            True if the download succeeded, False otherwise.
        """
        try:
            with self.page.expect_download(timeout=30000) as download_info:
                try:
                    self.page.goto(url, wait_until="commit", timeout=30000)
                except Exception as e:
                    # Navigation "fails" when download starts - this is expected.
                    if "Download is starting" in str(e):
                        self.logger.info("Download triggered successfully")
                    else:
                        raise

                download = download_info.value
                download.save_as(filepath)
                self.logger.info(f"Successfully downloaded PDF to {filepath}")
                return True

        except Exception as e:
            self.logger.error(f"Error downloading {doi} from {url}: {e}")
            return False

    # --- Wrap parent iteration with Playwright init/cleanup ---
    def download_all_papers(self) -> None:
        """
        Initialises the Playwright browser, delegates to the parent class iteration
        loop, and ensures the browser is cleaned up afterwards.
        """
        self._initialise_playwright()
        try:
            super().download_all_papers()
        finally:
            self.close()