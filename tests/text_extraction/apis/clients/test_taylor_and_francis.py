import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from text_extraction.apis.clients.taylor_and_francis import TaylorFrancisClient
from text_extraction.apis.abc.publisher_api import PublisherApi
from text_extraction.basemodels.publication import Publication


@pytest.fixture
def publications():
    return [
        Publication(doi=f"10.1080/0098791{i}", title=f"Test {i}", publisher="taylor_and_francis", year=2020)
        for i in range(3, 6)
    ]


class TestTaylorFrancisClient:

    def test_inherits_from_publisher_api(self, publications):
        client = TaylorFrancisClient(publications)
        assert isinstance(client, PublisherApi)

    def test_init_sets_name(self, publications):
        client = TaylorFrancisClient(publications)
        assert client.name == "taylor_and_francis"

    def test_download_paper_builds_correct_url(self, publications):
        client = TaylorFrancisClient(publications)
        doi = "10.1080/00987913.2018.1472477"

        with patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=True) as mock_dl:
            client.download_paper(doi)

        mock_dl.assert_called_once_with(
            doi=doi,
            url="https://www.tandfonline.com/doi/pdf/10.1080/00987913.2018.1472477",
            filepath=Path("/tmp/paper.pdf"),
        )

    def test_download_paper_success(self, publications):
        client = TaylorFrancisClient(publications)
        fake_path = Path("/tmp/paper.pdf")

        with patch.object(client, "_build_download_filepath", return_value=fake_path), \
             patch.object(client, "_attempt_download", return_value=True):
            result = client.download_paper("10.1080/00987913.2018.1472477")

        assert result == fake_path

    def test_download_paper_failure(self, publications):
        client = TaylorFrancisClient(publications)

        with patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=False):
            result = client.download_paper("10.1080/00987913.2018.1472477")

        assert result is None