import pytest
import requests.exceptions
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from biomarkit.text_download.apis.abc.publisher_api import PublisherApi
from tests.text_download.controller.test_controller import publications

# Mock the class.
class PublicationApiDummy(PublisherApi):

    """Minimal subclass for unit testing only."""
    def download_paper(self) -> None:
        pass

    def download_all_papers(self) -> None:
        pass

@patch("biomarkit.text_download.apis.abc.publisher_api.API_URL_TO_NAME", {"unpaywall": "https://api.unpaywall.org"})
@patch("biomarkit.text_download.apis.abc.publisher_api.API_KEY_TO_NAME", {"unpaywall": "fake-key"})
@patch("biomarkit.text_download.apis.abc.publisher_api.USER_EMAIL", "test@example.com")
def test___init__sets_attributes(publications, active_corpus):

    # Patch the _test_url check so __init__ passes.
    with patch.object(PublisherApi, "_test_url", return_value=True):
        api = PublicationApiDummy(name="unpaywall", publication_list=publications)

    assert api.name == "unpaywall"
    assert api.publication_list == publications
    assert api.email == "test@example.com"
    assert api.download_dir == active_corpus.download_dir
    assert api.api_url == "https://api.unpaywall.org"
    assert api.api_key == "fake-key"
    assert api.timeout == 10
    assert api.rate_limit_delay == 10.0

def test__setup_logger_follows_active_corpus(tmp_path):
    import logging
    from biomarkit.config import set_active_corpus

    set_active_corpus(tmp_path / "a")
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    set_active_corpus(tmp_path / "b")
    api = PublicationApiDummy(name="unpaywall", publication_list=[])

    file_handlers = [h for h in api.logger.handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    assert Path(file_handlers[0].baseFilename) == (tmp_path / "b" / "logs" / "unpaywall_client.log").resolve()

def test__init__raises_connection_error(publications):
    with patch.object(PublisherApi, "_test_url", return_value=False):
        with pytest.raises(ConnectionError):
            PublicationApiDummy(name="unpaywall", publication_list=publications)

def test__test_url_success():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = True

    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get", return_value=mock_response) as mock_get:
        result = api._test_url()

    mock_get.assert_called_once_with(api.api_url, timeout=api.timeout)
    assert result is True

def test__test_url_failure(publications):
    api = PublicationApiDummy(name="unpaywall", publication_list=publications)
    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get")as mock_get:
        mock_get.side_effect = requests.exceptions.RequestException("Network error")
        result = api._test_url()
        assert result is False

def test__build_download_filepath(active_corpus):
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    with patch("biomarkit.text_download.apis.abc.publisher_api.random.choices", return_value=list("1234567890")):
        path = api._build_download_filepath(filetype="pdf")

    assert isinstance(path, Path)
    assert path.parent == active_corpus.download_dir
    assert path.name == "unpaywall_1234567890.pdf"

def test__build_download_filepath_source_override():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    with patch("biomarkit.text_download.apis.abc.publisher_api.random.choices", return_value=list("1234567890")):
        path = api._build_download_filepath(filetype="pdf", source="arxiv")

    assert path.name == "arxiv_1234567890.pdf"

def test__attempt_download_all_scenarios(publications):
    api = PublicationApiDummy(name="unpaywall", publication_list=publications)
    doi = "10.1234/testdoi"
    url = "http://example.com/paper.pdf"
    filepath = "paper.pdf"

    # Success.
    with patch.object(api, "_download_paper_from_url", return_value=True):
        result = api._attempt_download(url=url, doi=doi, filepath=filepath)
        assert result is True

    # Body was the wrong file type, so nothing was written.
    with patch.object(api, "_download_paper_from_url", return_value=False):
        result = api._attempt_download(url=url, doi=doi, filepath=filepath)
        assert result is False

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
    mock_response.content = b"%PDF-DATA"
    mock_response.raise_for_status.return_value = None

    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get", return_value=mock_response) as mock_get, \
         patch("builtins.open", mock_open()) as mock_file:

        result = api._download_paper_from_url(url, filepath)

    assert result is True
    mock_get.assert_called_once_with(url, headers=None, timeout=api.timeout, allow_redirects=True)
    mock_file.assert_called_once_with(filepath, "wb")
    mock_file().write.assert_called_once_with(b"%PDF-DATA")


@pytest.mark.parametrize("content, filename, expected", [
    (b"<html>Access denied</html>", "paper.pdf", False),
    (b"\xef\xbb\xbf\n<?xml version='1.0'?><a/>", "paper.xml", True),
    (b"Access denied", "paper.xml", False),
])
def test__download_paper_from_url_checks_body_type(content, filename, expected):
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    mock_response = MagicMock()
    mock_response.content = content
    mock_response.raise_for_status.return_value = None

    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get", return_value=mock_response), \
         patch("builtins.open", mock_open()) as mock_file:
        result = api._download_paper_from_url("https://example.com/x", Path("/tmp") / filename)

    assert result is expected
    assert mock_file.called is expected


def test_download_all_papers_sleeps_between_papers_not_before_first(publications, tmp_path):
    api = PublicationApiDummy(name="unpaywall", publication_list=publications)
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 %%EOF")

    with patch.object(api, "download_paper", return_value=pdf), \
         patch.object(api, "_cache_successful_download"), \
         patch("biomarkit.text_download.apis.abc.publisher_api.time.sleep") as mock_sleep:
        PublisherApi.download_all_papers(api)

    assert mock_sleep.call_count == len(publications) - 1
    assert all(c.args == (api.rate_limit_delay,) for c in mock_sleep.call_args_list)

def test_download_paper_from_url_http_error():
    """Should raise if HTTP request fails."""
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    url = "https://example.com/404.pdf"
    filepath = Path("/tmp/paper.pdf")

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = Exception("404 Not Found")

    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get", return_value=mock_response):
        with pytest.raises(Exception, match="404 Not Found"):
            api._download_paper_from_url(url, filepath)

def test__download_pdf_if_valid_success():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])
    filepath = Path("/tmp/paper.pdf")

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.content = b"%PDF-1.7 pdf-bytes"

    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get", return_value=mock_response), \
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

    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get", return_value=mock_response), \
         patch("builtins.open", mock_open()) as mock_file:

        result = api._download_pdf_if_valid(url="https://example.com/paper.pdf", filepath=Path("/tmp/paper.pdf"))

    assert result is False
    mock_file.assert_not_called()

def test__download_pdf_if_valid_request_exception():
    api = PublicationApiDummy(name="unpaywall", publication_list=[])

    with patch("biomarkit.text_download.apis.abc.publisher_api.requests.get",
               side_effect=requests.exceptions.RequestException("Network error")):
        result = api._download_pdf_if_valid(url="https://example.com/paper.pdf", filepath=Path("/tmp/paper.pdf"))

    assert result is False

def test__cache_successful_download(publications, active_corpus):
    api = PublicationApiDummy(name="unpaywall", publication_list=publications)

    # Create a publication with a filepath.
    pub=publications[0]
    pdf = active_corpus.db.parent / "paper.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4 %%EOF")
    pub.publication_filepath = pdf

    # Success.
    with patch("biomarkit.text_download.apis.abc.publisher_api.insert_row", return_value=None) as mock_insert:
        api._cache_successful_download(pub)

        mock_insert.assert_called_once_with(
            doi=pub.doi,
            downloaded_from="unpaywall",
            publication_filepath="paper.pdf",
            db_path=active_corpus.db
        )

    # Failure.
    with pytest.raises(ValueError) as exc_info:
        api._cache_successful_download(publications[1])
