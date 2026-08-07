import sqlite3
from config import TMP_DIR
from text_download.database.database import create_database, insert_row, get_row_for_doi, update_content_json_filepath, update_final_md_filepath

def test_create_database_success():
    """
    Tests creating a new database, table existence and overwrite behaviour.
    """

    tmp_db_path = TMP_DIR / "tests_tmp/test.sqlite"
    create_database(db_path=tmp_db_path, del_existing=False)

    assert tmp_db_path.exists()

    # Check correct table exists.
    with sqlite3.connect(tmp_db_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cache'")
        result = cur.fetchone()
        assert result is not None, "Table 'cache' should exist"

def test_insert_row_success():
    tmp_db_path = TMP_DIR / "tests_tmp/test.sqlite"
    insert_row(doi="10.1234/abc", downloaded_from="example.com", publication_filepath="/path/to/file1", db_path=tmp_db_path)

    # Verify.
    conn = sqlite3.connect(tmp_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT doi, downloaded_from, publication_filepath FROM cache ORDER BY id")
    row = cursor.fetchone()
    conn.close()
    assert row is not None

def test_get_row_for_doi():
    tmp_db_path = TMP_DIR / "tests_tmp/test.sqlite"
    doi = "10.1234/abcd"
    insert_row(doi=doi, downloaded_from="example.com", publication_filepath="/path/to/file1", db_path=tmp_db_path)

    # Fetch.
    row = get_row_for_doi(doi=doi, db_path=tmp_db_path)

    # Check.
    assert row["doi"] == doi
    assert row["downloaded_from"] == "example.com"
    assert row["publication_filepath"] == "/path/to/file1"


def test_update_content_json_filepath(tmp_path):
    db = tmp_path / "test.db"
    create_database(db)
    insert_row("10.1/upd", "src", "/pub.xml", db)

    update_content_json_filepath("10.1/upd", "/path/to/content.json", db)

    row = get_row_for_doi("10.1/upd", db)
    assert row["content_json_filepath"] == "/path/to/content.json"


def test_update_final_md_filepath(tmp_path):
    db = tmp_path / "test.db"
    create_database(db)
    insert_row("10.1/md", "src", "/pub.xml", db)

    update_final_md_filepath("10.1/md", "/path/to/final.md", db)

    row = get_row_for_doi("10.1/md", db)
    assert row["final_md_filepath"] == "/path/to/final.md"


def test_update_both_filepath_columns(tmp_path):
    db = tmp_path / "test.db"
    create_database(db)
    insert_row("10.1/both", "src", "/pub.xml", db)

    update_content_json_filepath("10.1/both", "/json.json", db)
    update_final_md_filepath("10.1/both", "/final.md", db)

    row = get_row_for_doi("10.1/both", db)
    assert row["content_json_filepath"] == "/json.json"
    assert row["final_md_filepath"] == "/final.md"


def test_update_filepath_for_nonexistent_doi_is_noop(tmp_path):
    db = tmp_path / "test.db"
    create_database(db)

    # Should not raise even if the DOI doesn't exist.
    update_content_json_filepath("10.0/ghost", "/x.json", db)
    update_final_md_filepath("10.0/ghost", "/x.md", db)

    assert get_row_for_doi("10.0/ghost", db) is None
