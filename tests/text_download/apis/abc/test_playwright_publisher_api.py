import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock

from text_download.apis.abc.playwright_publisher_api import PlaywrightPublisherApi
from text_download.apis.abc.publisher_api import PublisherApi
from text_download.basemodels.publication import Publication


# --- Concrete dummy subclass (provides the abstract download_paper method) ---
class DummyPlaywrightClient(PlaywrightPublisherApi):
    def download_paper(self, doi: str):
        return None


# --- Fixtures ---
@pytest.fixture
def publications():
    return [
        Publication(doi="10.1234/test1", title="Test 1", publisher="test", year=2020),
        Publication(doi="10.1234/test2", title="Test 2", publisher="test", year=2021),
    ]


MODULE = "text_download.apis.abc.playwright_publisher_api"


def _make_client(publications):
    """Helper to build a DummyPlaywrightClient with all config patched out."""
    with patch(f"{MODULE}.API_URL_TO_NAME", {"unpaywall": "https://api.unpaywall.org/v2/"}), \
         patch("text_download.apis.abc.publisher_api.API_URL_TO_NAME", {"dummy": "http://dummy"}), \
         patch("text_download.apis.abc.publisher_api.API_KEY_TO_NAME", {"dummy": ""}), \
         patch("text_download.apis.abc.publisher_api.USER_EMAIL", "test@example.com"), \
         patch("text_download.apis.abc.publisher_api.DOWNLOAD_DIR", Path("/tmp/downloads")), \
         patch.object(PublisherApi, "_test_url", return_value=True):
        return DummyPlaywrightClient(name="dummy", publication_list=publications)


# ============================================================
# Tests
# ============================================================

class TestInit:
    def test_init_sets_playwright_attributes(self, publications):
        client = _make_client(publications)
        assert client._p is None
        assert client.browser is None
        assert client.context is None
        assert client.page is None
        assert client._initialized is False
        assert client.api_url == "https://api.unpaywall.org/v2/"

    def test_init_sets_base_attributes(self, publications):
        client = _make_client(publications)
        assert client.name == "dummy"
        assert client.publication_list == publications
        assert client.email == "test@example.com"


class TestTestUrl:
    def test_returns_true(self, publications):
        client = _make_client(publications)
        assert client._test_url() is True


class TestGetPdfUrl:
    def test_success(self, publications):
        client = _make_client(publications)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "best_oa_location": {"url_for_pdf": "https://example.com/paper.pdf"}
        }
        mock_resp.raise_for_status.return_value = None

        with patch(f"{MODULE}.requests.get", return_value=mock_resp):
            result = client._get_pdf_url("10.1234/test1")

        assert result == "https://example.com/paper.pdf"

    def test_no_oa_location(self, publications):
        client = _make_client(publications)
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"best_oa_location": None}
        mock_resp.raise_for_status.return_value = None

        with patch(f"{MODULE}.requests.get", return_value=mock_resp):
            result = client._get_pdf_url("10.1234/test1")

        # best_oa_location is None -> {}.get("url_for_pdf") -> None
        assert result is None

    def test_request_exception_returns_none(self, publications):
        """Verifies the bug fix: RequestException handler now returns None."""
        client = _make_client(publications)

        import requests as req
        with patch(f"{MODULE}.requests.get", side_effect=req.exceptions.RequestException("timeout")):
            result = client._get_pdf_url("10.1234/test1")

        assert result is None


class TestAttemptDownload:
    def test_success(self, publications):
        client = _make_client(publications)
        client.page = MagicMock()

        mock_download = MagicMock()
        download_ctx = MagicMock()
        download_ctx.__enter__ = MagicMock(return_value=download_ctx)
        download_ctx.__exit__ = MagicMock(return_value=False)
        download_ctx.value = mock_download
        client.page.expect_download.return_value = download_ctx

        result = client._attempt_download("10.1234/test1", "https://example.com/paper.pdf", "/tmp/paper.pdf")
        assert result is True
        mock_download.save_as.assert_called_once_with("/tmp/paper.pdf")

    def test_failure(self, publications):
        client = _make_client(publications)
        client.page = MagicMock()

        # Make expect_download raise an exception
        client.page.expect_download.side_effect = Exception("Download failed")

        result = client._attempt_download("10.1234/test1", "https://example.com/paper.pdf", "/tmp/paper.pdf")
        assert result is False


class TestClose:
    def test_close_cleans_up_browser(self, publications):
        client = _make_client(publications)

        mock_browser = MagicMock()
        mock_p = MagicMock()
        client.browser = mock_browser
        client._p = mock_p
        client.context = MagicMock()
        client.page = MagicMock()
        client._initialized = True

        client.close()

        mock_browser.close.assert_called_once()
        mock_p.stop.assert_called_once()
        assert client.browser is None
        assert client._p is None
        assert client.context is None
        assert client.page is None
        assert client._initialized is False

    def test_close_safe_when_not_initialized(self, publications):
        client = _make_client(publications)
        # Should not raise even when nothing is set.
        client.close()
        assert client._initialized is False


class TestDownloadAllPapers:
    def test_calls_initialise_and_super(self, publications):
        client = _make_client(publications)

        with patch.object(client, "_initialise_playwright") as mock_init, \
             patch.object(PublisherApi, "download_all_papers") as mock_super, \
             patch.object(client, "close") as mock_close:
            client.download_all_papers()

        mock_init.assert_called_once()
        mock_super.assert_called_once()
        mock_close.assert_called_once()

    def test_close_called_even_on_error(self, publications):
        client = _make_client(publications)

        with patch.object(client, "_initialise_playwright"), \
             patch.object(PublisherApi, "download_all_papers", side_effect=RuntimeError("boom")), \
             patch.object(client, "close") as mock_close:
            with pytest.raises(RuntimeError, match="boom"):
                client.download_all_papers()

        mock_close.assert_called_once()