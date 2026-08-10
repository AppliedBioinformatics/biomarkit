from tests.text_download.apis.abc.test_publisher_api import publications
from text_download.apis.clients.opensource import OpenSourceClient
from unittest.mock import MagicMock, patch, call
from requests.exceptions import RequestException
from pathlib import Path

# === Unpaywall fallback route ===
def test__get_pdf_url_prefers_url_for_pdf(publications):
    api = OpenSourceClient(publications)
    doi = "10.1234/testdoi"
    expected_url = "http://example.com/paper.pdf"

    with patch("text_download.apis.clients.opensource.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"best_oa_location": {"url_for_pdf": expected_url, "url": "http://example.com/landing"}}
        mock_get.return_value = mock_response
        assert api._get_pdf_url(doi) == expected_url

def test__get_pdf_url_falls_back_to_url(publications):
    api = OpenSourceClient(publications)
    doi = "10.1234/testdoi"
    landing_url = "http://example.com/landing"

    with patch("text_download.apis.clients.opensource.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"best_oa_location": {"url_for_pdf": None, "url": landing_url}}
        mock_get.return_value = mock_response
        assert api._get_pdf_url(doi) == landing_url

def test__get_pdf_url_no_oa_location(publications):
    api = OpenSourceClient(publications)
    doi = "10.1234/testdoi"

    with patch("text_download.apis.clients.opensource.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {}
        mock_get.return_value = mock_response
        assert api._get_pdf_url(doi) is None

def test__get_pdf_url_request_exception(publications, caplog):
    api = OpenSourceClient(publications)
    doi = "10.1234/testdoi"

    # Other network errors.
    with patch("text_download.apis.clients.opensource.requests.get") as mock_get:
        mock_get.side_effect = RequestException("Network error")

        with caplog.at_level("INFO", logger=api.logger.name):
            result = api._get_pdf_url(doi)
            assert result is None
            assert "Unable to retrieve url for DOI" in caplog.text

def test_download_paper_no_link(publications, caplog):
    api = OpenSourceClient(publications)
    doi = "10.1234/testdoi"

    with patch.object(api, "_get_pdf_url", return_value=None):
        with caplog.at_level("INFO", logger=api.logger.name):
            result = api.download_paper(doi)
            assert result is None
            assert f"No open access URL found for DOI: {doi}" in caplog.text

def test_download_paper_fails(publications, caplog):
    api = OpenSourceClient(publications)
    doi = "10.1234/testdoi"
    fake_url = "http://example.com/paper.pdf"
    fake_filepath = Path("/fake/path/paper.pdf")

    with patch.object(api, "_get_pdf_url", return_value=fake_url), \
            patch.object(api, "_build_download_filepath", return_value=fake_filepath), \
            patch.object(api, "_download_pdf_if_valid", return_value=False):

        with caplog.at_level("INFO", logger=api.logger.name):
            result = api.download_paper(doi)
            assert result is None

def test_download_paper_success(publications, caplog):
    api = OpenSourceClient(publication_list=publications)
    doi = "10.1234/testdoi"
    fake_url = "http://example.com/paper.pdf"
    fake_filepath = Path("/fake/path/paper.pdf")

    with patch.object(api, "_get_pdf_url", return_value=fake_url), \
            patch.object(api, "_build_download_filepath", return_value=fake_filepath), \
            patch.object(api, "_download_pdf_if_valid", return_value=True):

        with caplog.at_level("INFO", logger=api.logger.name):
            result = api.download_paper(doi)
            assert result == fake_filepath
            assert f"Paper downloaded for DOI: {doi} at filepath: {fake_filepath}" in caplog.text

# === arXiv route ===
def test__try_arxiv_no_match(publications):
    api = OpenSourceClient(publications)

    with patch.object(api, "_download_pdf_if_valid") as mock_download:
        # Non-arXiv DOI and old-style pre-2007 ID both fall through without a request.
        assert api._try_arxiv("10.1234/testdoi") is None
        assert api._try_arxiv("10.48550/arXiv.math/0211159") is None
        mock_download.assert_not_called()

def test__try_arxiv_success(publications):
    api = OpenSourceClient(publications)
    fake_filepath = Path("/fake/path/arxiv_1234567890.pdf")

    with patch.object(api, "_build_download_filepath", return_value=fake_filepath) as mock_build, \
            patch.object(api, "_download_pdf_if_valid", return_value=True) as mock_download:

        result = api._try_arxiv("10.48550/arXiv.2207.03928v2")

    assert result == fake_filepath
    mock_build.assert_called_once_with(source="arxiv")
    assert mock_download.call_args.kwargs["url"] == "https://arxiv.org/pdf/2207.03928v2.pdf"

def test__try_arxiv_download_fails(publications):
    api = OpenSourceClient(publications)

    with patch.object(api, "_build_download_filepath", return_value=Path("/fake/arxiv.pdf")), \
            patch.object(api, "_download_pdf_if_valid", return_value=False):

        assert api._try_arxiv("10.48550/arXiv.2207.03928") is None

# === bioRxiv route ===
def test__try_biorxiv_no_match(publications):
    api = OpenSourceClient(publications)

    with patch.object(api, "_download_pdf_if_valid") as mock_download:
        assert api._try_biorxiv("10.1234/testdoi") is None
        mock_download.assert_not_called()

def test__try_biorxiv_success(publications):
    api = OpenSourceClient(publications)
    doi = "10.1101/2024.01.01.573801"
    fake_filepath = Path("/fake/path/biorxiv_1234567890.pdf")

    with patch.object(api, "_build_download_filepath", return_value=fake_filepath) as mock_build, \
            patch.object(api, "_download_pdf_if_valid", return_value=True) as mock_download:

        result = api._try_biorxiv(doi)

    assert result == fake_filepath
    mock_build.assert_called_once_with(source="biorxiv")
    assert mock_download.call_args.kwargs["url"] == f"https://www.biorxiv.org/content/{doi}.full.pdf"

def test__try_biorxiv_falls_through_to_medrxiv(publications):
    api = OpenSourceClient(publications)
    doi = "10.1101/2024.02.02.24302345"
    fake_filepath = Path("/fake/path/medrxiv_1234567890.pdf")

    with patch.object(api, "_build_download_filepath", return_value=fake_filepath) as mock_build, \
            patch.object(api, "_download_pdf_if_valid", side_effect=[False, True]) as mock_download:

        result = api._try_biorxiv(doi)

    assert result == fake_filepath
    assert mock_build.call_args_list == [call(source="biorxiv"), call(source="medrxiv")]
    assert mock_download.call_args.kwargs["url"] == f"https://www.medrxiv.org/content/{doi}.full.pdf"

# === ChemRxiv route ===
def test__try_chemrxiv_no_match(publications):
    api = OpenSourceClient(publications)

    with patch.object(api, "_get_chemrxiv_item") as mock_item:
        assert api._try_chemrxiv("10.1234/testdoi") is None
        mock_item.assert_not_called()

def test__try_chemrxiv_success(publications):
    api = OpenSourceClient(publications)
    doi = "10.26434/chemrxiv-2021-np90x"
    fake_filepath = Path("/fake/path/chemrxiv_1234567890.pdf")
    item = {"asset": {"original": {"url": "http://example.com/chem.pdf"}}}

    with patch.object(api, "_get_chemrxiv_item", return_value=item), \
            patch.object(api, "_build_download_filepath", return_value=fake_filepath) as mock_build, \
            patch.object(api, "_download_pdf_if_valid", return_value=True) as mock_download:

        result = api._try_chemrxiv(doi)

    assert result == fake_filepath
    mock_build.assert_called_once_with(source="chemrxiv")
    assert mock_download.call_args.kwargs["url"] == "http://example.com/chem.pdf"

def test__try_chemrxiv_legacy_doi_retries_without_version(publications):
    api = OpenSourceClient(publications)
    doi = "10.26434/chemrxiv.14169658.v1"
    item = {"asset": {"url": "http://example.com/chem.pdf"}}

    with patch.object(api, "_get_chemrxiv_item", side_effect=[None, item]) as mock_item, \
            patch.object(api, "_build_download_filepath", return_value=Path("/fake/chem.pdf")), \
            patch.object(api, "_download_pdf_if_valid", return_value=True):

        result = api._try_chemrxiv(doi)

    assert result == Path("/fake/chem.pdf")
    assert mock_item.call_args_list == [call(doi), call("10.26434/chemrxiv.14169658")]

def test__try_chemrxiv_no_item(publications, caplog):
    api = OpenSourceClient(publications)
    doi = "10.26434/chemrxiv-2021-np90x"

    with patch.object(api, "_get_chemrxiv_item", return_value=None):
        with caplog.at_level("INFO", logger=api.logger.name):
            assert api._try_chemrxiv(doi) is None
            assert f"ChemRxiv API returned no item for DOI: {doi}" in caplog.text

def test__get_chemrxiv_item_unwraps_payload(publications):
    api = OpenSourceClient(publications)
    doi = "10.26434/chemrxiv-2021-np90x"

    with patch("text_download.apis.clients.opensource.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None

        # Bare item payload.
        mock_response.json.return_value = {"asset": {"url": "http://example.com/chem.pdf"}}
        mock_get.return_value = mock_response
        assert api._get_chemrxiv_item(doi) == {"asset": {"url": "http://example.com/chem.pdf"}}

        # Wrapped as {"item": {...}}.
        mock_response.json.return_value = {"item": {"asset": {}}}
        assert api._get_chemrxiv_item(doi) == {"asset": {}}

def test__get_chemrxiv_item_request_exception(publications):
    api = OpenSourceClient(publications)

    with patch("text_download.apis.clients.opensource.requests.get") as mock_get:
        mock_get.side_effect = RequestException("404 Not Found")
        assert api._get_chemrxiv_item("10.26434/chemrxiv-2021-np90x") is None

# === Route ordering ===
def test_download_paper_route_order(publications):
    api = OpenSourceClient(publications)
    doi = "10.1234/testdoi"
    manager = MagicMock()

    # No route succeeds - all four must be tried, in order.
    with patch.object(api, "_try_arxiv", return_value=None) as mock_arxiv, \
            patch.object(api, "_try_biorxiv", return_value=None) as mock_biorxiv, \
            patch.object(api, "_try_chemrxiv", return_value=None) as mock_chemrxiv, \
            patch.object(api, "_try_unpaywall", return_value=None) as mock_unpaywall:

        manager.attach_mock(mock_arxiv, "arxiv")
        manager.attach_mock(mock_biorxiv, "biorxiv")
        manager.attach_mock(mock_chemrxiv, "chemrxiv")
        manager.attach_mock(mock_unpaywall, "unpaywall")

        assert api.download_paper(doi) is None

    assert manager.mock_calls == [
        call.arxiv(doi), call.biorxiv(doi), call.chemrxiv(doi), call.unpaywall(doi),
    ]

def test_download_paper_short_circuits_on_first_success(publications):
    api = OpenSourceClient(publications)
    doi = "10.48550/arXiv.2207.03928"
    fake_filepath = Path("/fake/path/arxiv_1234567890.pdf")

    with patch.object(api, "_try_arxiv", return_value=fake_filepath), \
            patch.object(api, "_try_biorxiv") as mock_biorxiv, \
            patch.object(api, "_try_chemrxiv") as mock_chemrxiv, \
            patch.object(api, "_try_unpaywall") as mock_unpaywall:

        assert api.download_paper(doi) == fake_filepath

    mock_biorxiv.assert_not_called()
    mock_chemrxiv.assert_not_called()
    mock_unpaywall.assert_not_called()

# === Bulk download behaviour (inherited from PublisherApi) ===
def test_download_all_papers_success(publications):
    fake_path = MagicMock()
    api=OpenSourceClient(publication_list=publications)

    with patch.object(api, "download_paper", return_value=fake_path) as mock_download, \
            patch.object(api, "_cache_successful_download") as mock_cache:

        api.download_all_papers()
        assert mock_download.call_count == len(publications)
        assert mock_cache.call_count == len(publications)

        for pub in publications:
            assert pub.publication_filepath == fake_path

def test_download_papers_partial_failures(publications):
    api = OpenSourceClient(publication_list=publications)
    fake_path = MagicMock()
    side_effects = [fake_path, None, fake_path]

    with patch.object(api, "download_paper", side_effect=side_effects) as mock_download, \
            patch.object(api, "_cache_successful_download") as mock_cache:

        api.download_all_papers()
        assert mock_download.call_count == len(publications)
        assert mock_cache.call_count == 2
        assert publications[0].publication_filepath == fake_path
        assert publications[1].publication_filepath is None
        assert publications[2].publication_filepath == fake_path
