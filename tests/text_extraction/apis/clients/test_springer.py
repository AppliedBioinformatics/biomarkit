import pytest
from unittest.mock import patch
from pathlib import Path
from text_extraction.apis.clients.springer import SpringerClient
from tests.text_extraction.controller.test_controller import publications

def test_springer_client_init(publications):
        client = SpringerClient(publications)
        assert client.name == "springer"

def test_download_paper_failure(publications, caplog):
    doi = "10.1234/testdoi"
    fake_filepath = Path("/fake/path/test.pdf")

    client = SpringerClient(publications)
    with patch.object(client, "_build_download_filepath", return_value=fake_filepath), \
            patch.object(client, "_attempt_download", return_value=False):

        with caplog.at_level("INFO"):
            result = client.download_paper(doi)

        assert result is None
        assert f"Download attempt failed for {doi} from client: {client.name}" in caplog.text

def test_download_paper_success(publications, caplog):
    doi = "10.1234/testdoi"
    fake_filepath = Path("/fake/path/test.pdf")

    client = SpringerClient(publications)
    with patch.object(client, "_build_download_filepath", return_value=fake_filepath) as mock_build, \
         patch.object(client, "_attempt_download", return_value=True) as mock_download:

        with caplog.at_level("INFO", logger=client.logger.name):
            result = client.download_paper(doi)

        assert result == fake_filepath
        mock_build.assert_called_once()
        mock_download.assert_called_once_with(doi=doi,
                                              url=f"https://link.springer.com/content/pdf/{doi}.pdf",
                                              filepath=fake_filepath)