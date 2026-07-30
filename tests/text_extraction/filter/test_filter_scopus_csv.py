from text_extraction.filter.filter_scopus_csv import *
from text_extraction.filter.publisher_map import publisher_map
from config import BASE_DIR

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