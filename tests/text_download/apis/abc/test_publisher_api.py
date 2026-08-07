import pytest
import requests.exceptions
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from config import DB_CACHE_FILE_NAME
from text_download.apis.abc.publisher_api import PublisherApi
from tests.text_download.controller.test_controller import publications

# Mock the class.
class PublicationApiDummy(PublisherApi):

    """Minimal subclass for unit testing only."""
    def download_paper(self) -> None:
        pass

    def download_all_papers(self) -> None:
        pass

@patch("text_download.apis.abc.publisher_api.API_URL_TO_NAME", {"unpaywall": "https://api.unpaywall.org"})
@patch("text_download.apis.abc.publisher_api.API_KEY_TO_NAME", {"unpaywall": "fake-key"})
@patch("text_download.apis.abc.publisher_api.USER_EMAIL", "test@example.com")
@patch("text_download.apis.abc.publisher_api.DOWNLOAD_DIR", "/tmp/downloads")
def test___init__sets_attributes(publications):

    # Patch the _test_url check so __init__ passes.
    with patch.object(PublisherApi, "_test_url", return_value=True):
        api = PublicationApiDummy(name="unpaywall", publication_list=publications)

    assert api.name == "unpaywall"
    assert api.publication_list == publications
    assert api.email == "test@example.com"
    assert api.download_dir == "/tmp/downloads"
    assert api.api_url == "https://api.unpaywall.org"
    assert api.api_key == "fake-key"
    assert api.timeout == 10

def test__init__raises_connection_error(publications):
    with patch.object(PublisherApi, "_test_url", return_value=False):
        with pytest.raises(ConnectionError):
            PublicationApiDummy(name="unpaywall", publication_list=publications)

def test__test_url_success():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = True

    with patch("text_download.apis.abc.publisher_api.requests.get", return_value=mock_response) as mock_get:
        result = api._test_url()

    mock_get.assert_called_once_with(api.api_url)
    assert result is True

def test__test_url_failure(publications):
    api = PublicationApiDummy(name="unpaywall", publication_list=publications)
    with patch("text_download.apis.abc.publisher_api.requests.get")as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException("Network error")
        result = api._test_url()
        assert result is False

@patch("text_download.apis.abc.publisher_api.DOWNLOAD_DIR", Path("/tmp/downloads"))
def test__build_download_filepath():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    with patch("text_download.apis.abc.publisher_api.random.choices", return_value=list("1234567890")):
        path = api._build_download_filepath(filetype="pdf")

    assert isinstance(path, Path)
    assert path.parent == Path("/tmp/downloads")
    assert path.name == "unpaywall_1234567890.pdf"

@patch("text_download.apis.abc.publisher_api.DOWNLOAD_DIR", Path("/tmp/downloads"))
def test__build_download_filepath_source_override():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    with patch("text_download.apis.abc.publisher_api.random.choices", return_value=list("1234567890")):
        path = api._build_download_filepath(filetype="pdf", source="arxiv")

    assert path.name == "arxiv_1234567890.pdf"

def test__attempt_download_all_scenarios(publications):
    api = PublicationApiDummy(name="unpaywall", publication_list=publications)
    doi = "10.1234/testdoi"
    url = "http://example.com/paper.pdf"
    filepath = "paper.pdf"

    # Success.
    with patch.object(api, "_download_paper_from_url", return_value=None):
        result = api._attempt_download(url=url, doi=doi, filepath=filepath)
        assert result is True

    # HTTP error.
    with patch.object(api, "_download_paper_from_url", side_effect=requests.exceptions.HTTPError):
        result = api._attempt_download(url=url, doi=doi, filepath=filepath)
        assert result is False

    # SSL error.
    with patch.object(api, "_download_paper_from_url", side_effect=requests.exceptions.SSLError):
        result = api._attempt_download(url=url, doi=doi, filepath=filepath)
        assert result is False

    # Timeout, connection error, and excess redirects must all return False
    # (not None) so download_paper treats them as clean failures.
    for exc in (
        requests.exceptions.ReadTimeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.TooManyRedirects,
    ):
        with patch.object(api, "_download_paper_from_url", side_effect=exc):
            result = api._attempt_download(url=url, doi=doi, filepath=filepath)
            assert result is False, f"{exc.__name__} should return False"

def test__download_paper_from_url_success():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])

    url = "https://example.com/paper.pdf"
    filepath = Path("/tmp/paper.pdf")
    api.request_headers=None

    # Mock the HTTP response
    mock_response = MagicMock()
    mock_response.content = b"PDF-DATA"
    mock_response.raise_for_status.return_value = None

    with patch("text_download.apis.abc.publisher_api.requests.get", return_value=mock_response) as mock_get, \
         patch("builtins.open", mock_open()) as mock_file:

        api._download_paper_from_url(url, filepath)

    mock_get.assert_called_once_with(url, headers=None, timeout=api.timeout, allow_redirects=True)
    mock_file.assert_called_once_with(filepath, "wb")
    mock_file().write.assert_called_once_with(b"PDF-DATA")

def test_download_paper_from_url_http_error():
    """Should raise if HTTP request fails."""
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    url = "https://example.com/404.pdf"
    filepath = Path("/tmp/paper.pdf")

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("404 Not Found")

    with patch("text_download.apis.abc.publisher_api.requests.get", return_value=mock_response):
        with pytest.raises(Exception, match="404 Not Found"):
            api._download_paper_from_url(url, filepath)

def test__download_pdf_if_valid_success():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    filepath = Path("/tmp/paper.pdf")

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.content = b"%PDF-1.7 pdf-bytes"

    with patch("text_download.apis.abc.publisher_api.requests.get", return_value=mock_response), \
         patch("builtins.open", mock_open()) as mock_file:

        result = api._download_pdf_if_valid(url="https://example.com/paper.pdf", filepath=filepath)

    assert result is True
    mock_file.assert_called_once_with(filepath, "wb")
    mock_file().write.assert_called_once_with(b"%PDF-1.7 pdf-bytes")

def test__download_pdf_if_valid_rejects_non_pdf():
    """HTML failure pages come back as HTTP 200, so the %PDF magic-byte check must reject them."""
    api = PublicationApiDummy(name="unpaywall", publication_list=[])

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.content = b"<html>PDF unavailable</html>"

    with patch("text_download.apis.abc.publisher_api.requests.get", return_value=mock_response), \
         patch("builtins.open", mock_open()) as mock_file:

        result = api._download_pdf_if_valid(url="https://example.com/paper.pdf", filepath=Path("/tmp/paper.pdf"))

    assert result is False
    mock_file.assert_not_called()

def test__download_pdf_if_valid_request_exception():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])

    with patch("text_download.apis.abc.publisher_api.requests.get",
               side_effect=requests.exceptions.RequestException("Network error")):
        result = api._download_pdf_if_valid(url="https://example.com/paper.pdf", filepath=Path("/tmp/paper.pdf"))

    assert result is False

def test__cache_successful_download(publications):
    api = PublicationApiDummy(name="unpaywall", publication_list=publications)

    # Create a publication with a filepath.
    pub=publications[0]
    pub.publication_filepath=Path("paper.pdf")

    # Success.
    with patch("text_download.apis.abc.publisher_api.insert_row", return_value=None) as mock_insert:
        api._cache_successful_download(pub)

        mock_insert.assert_called_once_with(
            doi=pub.doi,
            downloaded_from="unpaywall",
            publication_filepath=str(pub.publication_filepath),
            db_path=DB_CACHE_FILE_NAME
        )

    # Failure.
    with pytest.raises(ValueError) as exc_info:
        api._cache_successful_download(publications[1])
