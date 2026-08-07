import pytest
from tests.text_download.controller.test_controller import publications
from unittest.mock import patch
from text_download.apis.clients.elsevier import ElsevierClient
from config import API_KEY_TO_NAME
from pathlib import Path

def test_elsevier_client_init(publications):
    with patch.dict(API_KEY_TO_NAME, {"elsevier": "test_api_key"}):
        client = ElsevierClient(publications)

        assert client.name == "elsevier"
        assert client.api_key == "test_api_key"
        assert client.request_headers == {
            "X-ELS-APIKey": "test_api_key",
            "Accept": "application/xml"
        }

def test_download_paper_failure(publications, caplog):
    client = ElsevierClient(publications)
    doi = "10.1234/testdoi"
    fake_filepath = Path("/fake/path/paper.pdf")

    with patch.object(client, "_build_download_filepath", return_value=fake_filepath), \
         patch.object(client, "_attempt_download", return_value=False):

        with caplog.at_level("INFO", logger=client.logger.name):
            results = client.download_paper(doi)

        assert results is None
        assert f"Download attempt failed for {doi}" in caplog.text

def test_download_paper_success(publications, caplog):
    client = ElsevierClient(publications)
    doi = "10.1234/testdoi"
    fake_filepath = Path("/fake/path/paper.pdf")

    with patch.object(client, "_build_download_filepath", return_value=fake_filepath) as mock_build, \
         patch.object(client, "_attempt_download", return_value=True) as mock_download:

        with caplog.at_level("INFO", logger=client.logger.name):
            result = client.download_paper(doi)

            assert result == fake_filepath
            mock_build.assert_called_once()
            mock_download.assert_called_once_with(doi=doi,
                                                  url=f"https://api.elsevier.com/content/article/doi/{doi}",
                                                  filepath=fake_filepath)

