import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from biomarkit.text_download.apis.clients.mdpi import MdpiClient
from biomarkit.text_download.apis.abc.playwright_publisher_api import PlaywrightPublisherApi
from biomarkit.text_download.basemodels.publication import Publication


@pytest.fixture
def publications():
    return [
        Publication(doi=f"10.1037/arc{i}", title=f"Test {i}", publisher="mdpi", year=2020)
        for i in range(14, 17)
    ]


class TestMdpiClient:

    def test_inherits_from_playwright_base(self, publications):
        client = MdpiClient(publications)
        assert isinstance(client, PlaywrightPublisherApi)

    def test_init_sets_name_and_timeout(self, publications):
        client = MdpiClient(publications)
        assert client.name == "mdpi"
        assert client.timeout == 1

    def test_download_paper_no_url_uses_fallback(self, publications):
        client = MdpiClient(publications)
        with patch.object(client, "_get_pdf_url", return_value=None), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/p.pdf")), \
             patch.object(client, "attempt_fallback", return_value=True) as mock_fb:
            result = client.download_paper("10.1234/test")
        mock_fb.assert_called_once_with(doi="10.1234/test", filepath=Path("/tmp/p.pdf"))
        assert result == Path("/tmp/p.pdf")

    def test_download_paper_no_url_and_fallback_fails(self, publications):
        client = MdpiClient(publications)
        with patch.object(client, "_get_pdf_url", return_value=None), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/p.pdf")), \
             patch.object(client, "attempt_fallback", return_value=False):
            result = client.download_paper("10.1234/test")
        assert result is None

    def test_download_paper_download_fails_then_fallback_fails(self, publications):
        client = MdpiClient(publications)
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=False), \
             patch.object(client, "attempt_fallback", return_value=False) as mock_fb:
            result = client.download_paper("10.1234/test")
        mock_fb.assert_called_once()
        assert result is None

    def test_download_paper_download_fails_then_fallback_succeeds(self, publications):
        client = MdpiClient(publications)
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=False), \
             patch.object(client, "attempt_fallback", return_value=True):
            result = client.download_paper("10.1234/test")
        assert result == Path("/tmp/paper.pdf")

    def test_download_paper_success_skips_fallback(self, publications):
        client = MdpiClient(publications)
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=True), \
             patch.object(client, "attempt_fallback") as mock_fb:
            client.download_paper("10.1234/test")
        mock_fb.assert_not_called()

    def test_attempt_fallback_downloads_article_pdf_in_browser(self, publications):
        client = MdpiClient(publications)
        client.page = MagicMock()
        client.page.url = "https://www.mdpi.com/2223-7747/14/18/2820?utm=x#sec1"
        with patch.object(client, "_attempt_download", return_value=True) as mock_dl:
            assert client.attempt_fallback("10.3390/plants14182820", "/tmp/p.pdf") is True
        client.page.goto.assert_called_once()
        assert client.page.goto.call_args.args[0] == "https://doi.org/10.3390/plants14182820"
        mock_dl.assert_called_once_with(
            doi="10.3390/plants14182820", url="https://www.mdpi.com/2223-7747/14/18/2820/pdf", filepath="/tmp/p.pdf"
        )

    def test_attempt_fallback_rejects_non_mdpi_page(self, publications):
        client = MdpiClient(publications)
        client.page = MagicMock()
        client.page.url = "https://www.example.org/some-article"
        with patch.object(client, "_attempt_download") as mock_dl:
            assert client.attempt_fallback("10.1234/test", "/tmp/p.pdf") is False
        mock_dl.assert_not_called()

    def test_attempt_fallback_navigation_error(self, publications):
        client = MdpiClient(publications)
        client.page = MagicMock()
        client.page.goto.side_effect = Exception("Timeout 30000ms exceeded")
        with patch.object(client, "_attempt_download") as mock_dl:
            assert client.attempt_fallback("10.1234/test", "/tmp/p.pdf") is False
        mock_dl.assert_not_called()

    def test_download_paper_success(self, publications):
        client = MdpiClient(publications)
        fake_path = Path("/tmp/paper.pdf")
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=fake_path), \
             patch.object(client, "_attempt_download", return_value=True):
            result = client.download_paper("10.1234/test")
        assert result == fake_path