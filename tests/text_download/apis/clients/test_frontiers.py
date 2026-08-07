import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from requests.exceptions import RequestException
from text_download.apis.clients.frontiers import FrontiersClient
from text_download.apis.abc.playwright_publisher_api import PlaywrightPublisherApi
from text_download.basemodels.publication import Publication


@pytest.fixture
def publications():
    return [
        Publication(doi=f"10.1037/arc{i}", title=f"Test {i}", publisher="frontiers", year=2020)
        for i in range(14, 17)
    ]


class TestFrontiersClient:

    def test_inherits_from_playwright_base(self, publications):
        client = FrontiersClient(publications)
        assert isinstance(client, PlaywrightPublisherApi)

    def test_init_sets_name_and_timeout(self, publications):
        client = FrontiersClient(publications)
        assert client.name == "frontiers"
        assert client.timeout == 5

    def test_download_paper_no_url_uses_fallback(self, publications):
        client = FrontiersClient(publications)
        with patch.object(client, "_get_pdf_url", return_value=None), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/p.pdf")), \
             patch.object(client, "attempt_fallback", return_value=True) as mock_fb:
            result = client.download_paper("10.1234/test")
        mock_fb.assert_called_once_with(doi="10.1234/test", filepath=Path("/tmp/p.pdf"))
        assert result == Path("/tmp/p.pdf")

    def test_download_paper_fallback_also_fails(self, publications):
        client = FrontiersClient(publications)
        with patch.object(client, "_get_pdf_url", return_value=None), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/p.pdf")), \
             patch.object(client, "attempt_fallback", return_value=False):
            result = client.download_paper("10.1234/test")
        assert result is None

    def test_download_paper_with_url_success(self, publications):
        client = FrontiersClient(publications)
        fake_path = Path("/tmp/paper.pdf")
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=fake_path), \
             patch.object(client, "_attempt_download", return_value=True):
            result = client.download_paper("10.1234/test")
        assert result == fake_path

    def test_download_paper_with_url_failure(self, publications):
        client = FrontiersClient(publications)
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/p.pdf")), \
             patch.object(client, "_attempt_download", return_value=False):
            result = client.download_paper("10.1234/test")
        assert result is None

    def test_attempt_fallback_success(self, publications):
        client = FrontiersClient(publications)
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"PDF-DATA"]

        with patch("text_download.apis.clients.frontiers.requests.get", return_value=mock_resp), \
             patch("builtins.open", MagicMock()):
            result = client.attempt_fallback("10.1234/test", "/tmp/p.pdf")
        assert result is True

    def test_attempt_fallback_request_error(self, publications):
        client = FrontiersClient(publications)
        with patch("text_download.apis.clients.frontiers.requests.get",
                   side_effect=RequestException("fail")):
            result = client.attempt_fallback("10.1234/test", "/tmp/p.pdf")
        assert result is False