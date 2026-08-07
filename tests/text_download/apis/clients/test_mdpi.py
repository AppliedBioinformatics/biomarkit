import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from text_download.apis.clients.mdpi import MdpiClient
from text_download.apis.abc.playwright_publisher_api import PlaywrightPublisherApi
from text_download.basemodels.publication import Publication


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

    def test_download_paper_no_url(self, publications):
        client = MdpiClient(publications)
        with patch.object(client, "_get_pdf_url", return_value=None):
            result = client.download_paper("10.1234/test")
        assert result is None

    def test_download_paper_download_fails(self, publications):
        client = MdpiClient(publications)
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=False):
            result = client.download_paper("10.1234/test")
        assert result is None

    def test_download_paper_success(self, publications):
        client = MdpiClient(publications)
        fake_path = Path("/tmp/paper.pdf")
        with patch.object(client, "_get_pdf_url", return_value="http://example.com/paper.pdf"), \
             patch.object(client, "_build_download_filepath", return_value=fake_path), \
             patch.object(client, "_attempt_download", return_value=True):
            result = client.download_paper("10.1234/test")
        assert result == fake_path