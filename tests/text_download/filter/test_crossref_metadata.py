from unittest.mock import MagicMock, patch

from requests.exceptions import RequestException

from biomarkit.text_download.filter.crossref_metadata import fetch_crossref_metadata, read_dois

_GET = "biomarkit.text_download.filter.crossref_metadata.requests.get"


def _response(items):
    resp = MagicMock()
    resp.json.return_value = {"message": {"items": items}}
    return resp


def _item(doi, title="A title", year=2020, publisher="Elsevier BV", abstract=None):
    item = {"DOI": doi, "title": [title], "issued": {"date-parts": [[year, 1, 1]]}, "publisher": publisher}
    if abstract:
        item["abstract"] = abstract
    return item


def test_read_dois_list_strips_prefixes_and_duplicates():
    dois = [" https://doi.org/10.1016/A ", "doi:10.1007/b", "10.1016/a", "http://dx.doi.org/10.3390/c", ""]
    assert read_dois(dois) == ["10.1016/A", "10.1007/b", "10.3390/c"]


def test_read_dois_file(tmp_path):
    path = tmp_path / "dois.txt"
    path.write_text("# my DOIs\n10.1016/a\n\n  10.1007/b  \n# 10.9999/skipped\n", encoding="utf-8")
    assert read_dois(path) == ["10.1016/a", "10.1007/b"]
    assert read_dois(str(path)) == ["10.1016/a", "10.1007/b"]


def test_fetch_batches_and_keeps_input_spelling():
    dois = ["10.1016/J.A", "10.1007/b", "10.3390/c"]
    with patch(_GET, side_effect=[_response([_item("10.1016/j.a"), _item("10.1007/b", year=2019)]),
                                  _response([_item("10.3390/c", publisher="MDPI AG")])]) as mock_get:
        df = fetch_crossref_metadata(dois, batch_size=2)

    assert mock_get.call_count == 2
    assert mock_get.call_args_list[0].kwargs["params"]["filter"] == "doi:10.1016/J.A,doi:10.1007/b"
    assert mock_get.call_args_list[1].kwargs["params"]["filter"] == "doi:10.3390/c"
    assert list(df.columns) == ["Title", "Year", "DOI", "Publisher", "Abstract"]
    assert df["DOI"].tolist() == dois
    assert df["Year"].tolist() == [2020, 2019, 2020]
    assert df["Publisher"].tolist() == ["Elsevier BV", "Elsevier BV", "MDPI AG"]


def test_fetch_strips_jats_abstract():
    abstract = "<jats:title>Abstract</jats:title><jats:p>Wheat stripe\n rust <jats:italic>Pst</jats:italic>.</jats:p>"
    with patch(_GET, return_value=_response([_item("10.1016/a", abstract=abstract)])):
        df = fetch_crossref_metadata(["10.1016/a"])
    assert df.loc[0, "Abstract"] == "Abstract Wheat stripe rust Pst ."


def test_fetch_drops_unresolved_and_incomplete(caplog):
    items = [_item("10.1016/a"), {"DOI": "10.1007/b", "title": [], "issued": {"date-parts": [[2020]]}},
             {"DOI": "10.3390/c", "title": ["T"], "issued": {"date-parts": [[None]]}}]
    with patch(_GET, return_value=_response(items)):
        with caplog.at_level("WARNING"):
            df = fetch_crossref_metadata(["10.1016/a", "10.1007/b", "10.3390/c", "10.48550/arXiv.2207.03928"])

    assert df["DOI"].tolist() == ["10.1016/a"]
    assert "10.1007/b, 10.3390/c, 10.48550/arXiv.2207.03928" in caplog.text


def test_fetch_retries_failed_batch_once():
    with patch(_GET, side_effect=[RequestException("500"), _response([_item("10.1016/a")])]) as mock_get:
        df = fetch_crossref_metadata(["10.1016/a"])
    assert mock_get.call_count == 2
    assert df["DOI"].tolist() == ["10.1016/a"]

    with patch(_GET, side_effect=RequestException("500")) as mock_get:
        df = fetch_crossref_metadata(["10.1016/a"])
    assert mock_get.call_count == 2
    assert df.empty
