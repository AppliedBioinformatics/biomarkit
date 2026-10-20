from biomarkit.text_download.filter.filter_scopus_csv import *
from biomarkit.text_download.filter.publisher_map import publisher_map
from biomarkit.config import BASE_DIR

def test_load_scopus_csv():
    test_data = BASE_DIR / "tests" / "test_data" / "scopus_test_query.csv"
    df = load_scopus_csv(test_data)

    assert type(df) == pd.DataFrame
    assert df.shape[0] == 100
    for i in ["Title", "Year", "DOI", "Publisher"]:
        assert i in df.columns

def test_synchronise_publishers():
    # Custom small db.
    test_data = BASE_DIR / "tests" / "test_data" / "scopus_test_query.csv"
    raw_df = load_scopus_csv(test_data)
    raw_df = remove_imperfect_rows(raw_df)

    # Assert Rows with NA values are dropped.
    df = synchronise_publishers(raw_df, mapper=publisher_map, column="Publisher")

    # Assert generics.
    assert type(df) == pd.DataFrame
    assert df.shape[0] == raw_df.shape[0]
    assert df.shape[1] == raw_df.shape[1] + 1

    # Check examples do not exist.
    for p in ["Elsevier B.V", "Elsevier GmbH", "Nature Publishing Group", "John Wiley and Sons Inc"]:
        assert p not in df["Publisher"]

    # Check redundant values have been replaced.
    for i in ["wiley", "nature", "springer", "elsevier"]:
        df["Publisher"].str.contains(i, case=False, na=False).any()

def test_build_publication_objects():
    test_data = BASE_DIR / "tests" / "test_data" / "scopus_test_query.csv"
    raw_df = load_scopus_csv(test_data)
    raw_df = remove_imperfect_rows(raw_df)
    df = synchronise_publishers(raw_df, mapper=publisher_map, column="Publisher")

    # Build publication objects.
    res = build_publication_objects(df)

    # Generic asserts.
    assert type(res) == list
    assert len(res) == df.shape[0]

    for p in res[:10]:
        assert type(p) == Publication

# ---------------------------------------------------------------------------
# Missing publishers and DOI-prefix inference
# ---------------------------------------------------------------------------

import logging
import pytest
from biomarkit.text_download.filter.doi_prefix_map import doi_prefix_map


def _df(rows):
    return pd.DataFrame(rows, columns=["Title", "Year", "DOI", "Publisher", "Abstract"])


def test_remove_imperfect_rows_keeps_rows_missing_publisher_or_abstract():
    df = _df([
        ["A", 2020, "10.1016/a", None, "abs"],
        ["B", 2021, "10.1007/b", "Springer", None],
    ])
    assert len(remove_imperfect_rows(df)) == 2


@pytest.mark.parametrize("column", ["DOI", "Title", "Year"])
def test_remove_imperfect_rows_drops_rows_missing_required_fields(column):
    row = {"Title": "A", "Year": 2020, "DOI": "10.1016/a", "Publisher": "Elsevier", "Abstract": "x"}
    row[column] = None
    df = _df([list(row.values()), ["B", 2021, "10.1007/b", "Springer", "y"]])
    out = remove_imperfect_rows(df)
    assert out["DOI"].tolist() == ["10.1007/b"]


def test_remove_imperfect_rows_strips_and_deduplicates_dois():
    df = _df([
        ["A", 2020, " 10.1016/a ", "Elsevier", "x"],
        ["A again", 2020, "10.1016/a", "Elsevier", "x"],
    ])
    out = remove_imperfect_rows(df)
    assert out["DOI"].tolist() == ["10.1016/a"]
    assert out["Title"].tolist() == ["A"]


@pytest.mark.parametrize("doi, expected", [
    ("10.1016/j.cell.2025.05.028", "elsevier"),
    ("10.1006/abcd.1999.1", "elsevier"),
    ("10.1007/s00122-020-1", "springer"),
    ("10.1038/s41586-020-1", "springer"),
    ("10.1186/s12915-024-02081-y", "springer"),
    ("10.1111/pce.1234", "wiley"),
    ("10.2135/cropsci2010.01.0001", "wiley"),
    ("10.1080/00103624.2020.1", "taylor_and_francis"),
    ("10.3390/plants14182820", "mdpi"),
    ("10.3389/fpls.2022.994154", "frontiers"),
    ("10.5194/bg-1-2020", "copernicus"),
    ("10.1094/PDIS-01-20-0001-RE", "american_phytopathological_society"),
    (" 10.1016/a ", "elsevier"),
])
def test_infer_publisher_from_doi_known_prefixes(doi, expected):
    assert infer_publisher_from_doi(doi) == expected


@pytest.mark.parametrize("doi", ["10.1093/jxb/abc", "10.1071/fp1", "not-a-doi", "", None, float("nan")])
def test_infer_publisher_from_doi_unknown_or_invalid(doi):
    assert infer_publisher_from_doi(doi) is None


def test_doi_prefix_map_keys_are_api_clients():
    from biomarkit.text_download.apis.map import api_clients
    assert set(doi_prefix_map) <= set(api_clients)


def test_doi_prefixes_are_unique():
    prefixes = [p for ps in doi_prefix_map.values() for p in ps]
    assert len(prefixes) == len(set(prefixes))


def _sync(rows, **kwargs):
    return synchronise_publishers(remove_imperfect_rows(_df(rows)), **kwargs).set_index("DOI")["PublisherGroup"]


def test_synchronise_publishers_fills_missing_publisher_from_doi():
    groups = _sync([["A", 2020, "10.1016/a", None, "x"]])
    assert groups["10.1016/a"] == "elsevier"


def test_synchronise_publishers_replaces_unrecognised_publisher_from_doi():
    groups = _sync([["A", 2020, "10.1007/a", "Springer Singapore", "x"]])
    assert groups["10.1007/a"] == "springer"


def test_synchronise_publishers_never_overrides_recognised_publisher():
    # Recognised Scopus name wins even if the prefix belongs to another client.
    groups = _sync([["A", 2020, "10.1016/a", "John Wiley and Sons Inc", "x"]])
    assert groups["10.1016/a"] == "wiley"


def test_synchronise_publishers_unknown_prefix_and_no_publisher_is_unknown():
    groups = _sync([["A", 2020, "10.1093/a", None, "x"]])
    assert groups["10.1093/a"] == "unknown"


def test_synchronise_publishers_unknown_prefix_keeps_unrecognised_name():
    groups = _sync([["A", 2020, "10.1071/a", "CSIRO Publishing", "x"]])
    assert groups["10.1071/a"] == "CSIRO Publishing"


def test_synchronise_publishers_inference_can_be_disabled():
    groups = _sync([
        ["A", 2020, "10.1016/a", None, "x"],
        ["B", 2020, "10.1007/b", "Springer Singapore", "x"],
    ], infer_from_doi=False)
    assert groups["10.1016/a"] == "unknown"
    assert groups["10.1007/b"] == "Springer Singapore"


def test_synchronise_publishers_logs_inference_counts(caplog):
    with caplog.at_level(logging.INFO):
        _sync([
            ["A", 2020, "10.1016/a", None, "x"],
            ["B", 2020, "10.1007/b", "Springer Singapore", "x"],
            ["C", 2020, "10.1111/c", "John Wiley and Sons Inc", "x"],
        ])
    assert "for 2 row(s) (1 had no publisher, 1 were unrecognised)" in caplog.text


def test_build_publication_objects_nan_abstract_becomes_none():
    df = synchronise_publishers(remove_imperfect_rows(_df([["A", 2020, "10.1016/a", "Elsevier", None]])))
    assert build_publication_objects(df)[0].abstract is None


def test_build_publication_objects_skips_invalid_rows(caplog):
    bad_doi = "10.3398/1527-0904(2007)67[299:EOPFBO]2.0.CO;2"
    df = synchronise_publishers(remove_imperfect_rows(_df([
        ["A", 2020, "10.1016/a", "Elsevier", "x"],
        ["Bad", 2020, bad_doi, None, "x"],
        ["C", 2021, "10.1007/c", "Springer", "y"],
    ])))
    with caplog.at_level(logging.WARNING):
        pubs = build_publication_objects(df)
    assert [p.doi for p in pubs] == ["10.1016/a", "10.1007/c"]
    assert bad_doi in caplog.text
