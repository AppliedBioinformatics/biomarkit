import pytest
from unittest.mock import patch, MagicMock
from tests.text_download.controller.test_controller import publications
from text_download.apis.clients.wiley import WileyClient
from config import TMP_DIR
from pathlib import Path

def test_wiley_client_init(publications, caplog):
    fake_tdm_client = MagicMock()

    with patch("text_download.apis.clients.wiley.TDMClient", return_value=fake_tdm_client) as mock_tdm, \
         patch("text_download.apis.clients.wiley.WILEY_TDM_TOKEN", "test_token"):

        with caplog.at_level("INFO"):
            client = WileyClient(publication_list=publications)

        # Check that connect_wiley_tdm was called via __init__
        mock_tdm.assert_called_once_with(api_token="test_token", download_dir=TMP_DIR)
        assert client.wiley_client == fake_tdm_client
        assert "Connected to Wiley via TDM." in caplog.text

def test_wiley_client_missing_token(publications):
    # Patch the token to None
    with patch("text_download.apis.clients.wiley.WILEY_TDM_TOKEN", None):
        with pytest.raises(ValueError, match="WILEY_TDM_TOKEN environment variable not set"):
            WileyClient(publication_list=publications)

def test__test_url(publications):
    client = WileyClient(publication_list=publications)
    assert client._test_url() == True

def test__move_file(publications, caplog):
    tmp_path = Path("/tmp/test.pdf")
    final_path = Path("/downloads/test_final.pdf")

    client=WileyClient(publication_list=publications)
    with patch.object(client, "_build_download_filepath", return_value=final_path), \
            patch("shutil.move") as mock_shutil_move:

        with caplog.at_level("DEBUG", logger="PublisherApi.wiley"):
            result = client._move_file(tmp_path)

    mock_shutil_move.assert_called_once_with(str(tmp_path), str(final_path))
    assert result == final_path
    assert f"Moving Wiley paper from TMP: {tmp_path} to DOWNLOADS: {final_path}" in caplog.text
    assert "Move completed." in caplog.text

def test_download_paper_failure_status(publications, caplog):
    doi = "10.1234/testdoi"
    fake_result = MagicMock()
    fake_result.status = "Failed"
    fake_result.path = "/fake/path/test.pdf"

    client = WileyClient(publication_list=publications)
    client.wiley_client.download_pdf = MagicMock(return_value=fake_result)

    with caplog.at_level("INFO"):
        result = client.download_paper(doi)

    assert result is None
    assert f"Unable to download Publication for DOI: {doi} using Wiley API." in caplog.text

def test_download_paper_failure_file_missing(publications, caplog):
    doi = "10.1234/testdoi"
    fake_result = MagicMock()
    fake_result.status = "Success"
    fake_result.path = "/fake/path/test.pdf"

    # Patch Path.exists to return False
    client = WileyClient(publication_list=publications)
    with patch("pathlib.Path.exists", return_value=False):
        client.wiley_client.download_pdf = MagicMock(return_value=fake_result)
        result = client.download_paper(doi)

    # Assert None is returned because the file doesn't exist
    assert result is None

def test_download_paper_success(publications, caplog):
    doi = "10.1234/testdoi"
    fake_result = MagicMock()
    fake_result.status = "Success"
    fake_result.path = "/fake/path/test.pdf"
    fake_filepath = Path("/final/path/test.pdf")
    client = WileyClient(publication_list=publications)

    # Mocks.
    client.wiley_client.download_pdf = MagicMock(return_value=fake_result)
    client._move_file = MagicMock(return_value=fake_filepath)

    with patch("pathlib.Path.exists", return_value=True):
        with caplog.at_level("INFO"):
            result = client.download_paper(doi)

    # Assert the returned filepath
    assert result == fake_filepath

    # Assert _move_file was called with the correct path
    client._move_file.assert_called_once_with(current_path=fake_result.path)

    # Check log messages
    assert f"Attempting to download paper for doi: {doi} using Wiley API." in caplog.text
    assert f"Downloaded Publication for DOI: {doi} to {fake_filepath} from Wiley API." in caplog.text