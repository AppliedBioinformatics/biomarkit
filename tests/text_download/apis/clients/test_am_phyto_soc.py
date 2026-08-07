import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from text_download.apis.clients.am_phyto_soc import AmPhytoSocClient
from text_download.apis.abc.publisher_api import PublisherApi
from text_download.basemodels.publication import Publication


@pytest.fixture
def publications():
    return [
        Publication(doi=f"10.1094/PHYTO-{i}", title=f"Test {i}", publisher="american_phytopathological_society", year=2020)
        for i in range(14, 17)
    ]


class TestAmPhytoSocClient:

    def test_inherits_from_publisher_api(self, publications):
        client = AmPhytoSocClient(publications)
        assert isinstance(client, PublisherApi)

    def test_init_sets_name(self, publications):
        client = AmPhytoSocClient(publications)
        assert client.name == "american_phytopathological_society"

    def test_download_paper_builds_correct_url(self, publications):
        client = AmPhytoSocClient(publications)
        doi = "10.1094/PHYTO-10-21-0430-PER"

        with patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=True) as mock_dl:
            client.download_paper(doi)

        mock_dl.assert_called_once_with(
            doi=doi,
            url="https://apsjournals.apsnet.org/doi/pdf/10.1094/PHYTO-10-21-0430-PER",
            filepath=Path("/tmp/paper.pdf"),
        )

    def test_download_paper_success(self, publications):
        client = AmPhytoSocClient(publications)
        fake_path = Path("/tmp/paper.pdf")

        with patch.object(client, "_build_download_filepath", return_value=fake_path), \
             patch.object(client, "_attempt_download", return_value=True):
            result = client.download_paper("10.1094/PHYTO-10-21-0430-PER")

        assert result == fake_path

    def test_download_paper_failure(self, publications):
        client = AmPhytoSocClient(publications)

        with patch.object(client, "_build_download_filepath", return_value=Path("/tmp/paper.pdf")), \
             patch.object(client, "_attempt_download", return_value=False):
            result = client.download_paper("10.1094/PHYTO-10-21-0430-PER")

        assert result is None