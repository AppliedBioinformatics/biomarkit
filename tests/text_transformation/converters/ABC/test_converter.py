import sqlite3
import pytest
import os
from pathlib import Path
from config import TMP_DIR
from text_extraction.basemodels.publication import Publication
from text_extraction.database.database import create_database, get_row_for_doi

TMP_DB = TMP_DIR / "tests_tmp" / "test_converter.sqlite"

DB_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT UNIQUE NOT NULL,
    downloaded_from TEXT NOT NULL,
    publication_filepath TEXT NOT NULL,
    content_json_filepath TEXT,
    final_md_filepath TEXT)
"""


def _setup_db(rows: list[dict]) -> None:
    """Creates a fresh test DB and inserts the given rows."""
    TMP_DB.parent.mkdir(parents=True, exist_ok=True)
    if TMP_DB.exists():
        TMP_DB.unlink()
    with sqlite3.connect(TMP_DB) as conn:
        conn.execute(DB_SCHEMA)
        conn.executemany(
            "INSERT INTO cache "
            "(doi, downloaded_from, publication_filepath, content_json_filepath, final_md_filepath) "
            "VALUES (:doi, :downloaded_from, :publication_filepath, :content_json_filepath, :final_md_filepath)",
            rows,
        )


def _make_pub(doi: str, tmp_path: Path) -> Publication:
    """Builds a cached Publication with a real temp file as publication_filepath."""
    pub_file = tmp_path / f"{doi.replace('/', '_')}.xml"
    pub_file.touch()
    return Publication(doi=doi, title="Test", publisher="TestPublisher",
                       year=2020, publication_filepath=pub_file)


# ---------------------------------------------------------------------------
# Minimal concrete subclass for testing
# ---------------------------------------------------------------------------

def _make_converter_class(convert_fn):
    """
    Returns a concrete Converter subclass whose convert() delegates to convert_fn.
    Allows different convert() behaviours per test without boilerplate.
    """
    from text_transformation.converters.ABC.converter import Converter

    class _TestConverter(Converter):
        def convert(self, pub):
            return convert_fn(pub)

    return _TestConverter


# ---------------------------------------------------------------------------
# _build_output_path
# ---------------------------------------------------------------------------

def test_build_output_path_places_json_in_auto_subdir(tmp_path):
    """Output path is output_dir/<stem>/auto/<stem>_content_list_v2.json."""
    pub = _make_pub("10.1037/bp1", tmp_path)
    stem = pub.publication_filepath.stem

    cls = _make_converter_class(lambda p: None)
    converter = cls(publication_list=[pub])
    converter.output_dir = tmp_path

    result = converter._build_output_path(pub)

    assert result == tmp_path / stem / "auto" / f"{stem}_content_list_v2.json"


def test_default_output_dir_is_raw_markdown_dir():
    """Default output_dir is RAW_MARKDOWN_DIR."""
    from config import RAW_MARKDOWN_DIR
    cls = _make_converter_class(lambda p: None)
    converter = cls(publication_list=[])
    assert converter.output_dir == RAW_MARKDOWN_DIR


# ---------------------------------------------------------------------------
# _cache_result
# ---------------------------------------------------------------------------

def test_cache_result_writes_content_json_filepath_to_db(tmp_path):
    pub = _make_pub("10.1037/cr1", tmp_path)
    raw_md = tmp_path / "output.md"
    raw_md.touch()

    _setup_db([{
        "doi": pub.doi,
        "downloaded_from": "publisher",
        "publication_filepath": str(pub.publication_filepath),
        "content_json_filepath": None,
        "final_md_filepath": None,
    }])

    pub.content_json_filepath = raw_md

    from text_transformation.converters.ABC.converter import Converter
    cls = _make_converter_class(lambda p: None)
    converter = cls(publication_list=[pub])
    converter.cache = TMP_DB
    converter._cache_result(pub)

    row = get_row_for_doi(pub.doi, TMP_DB)
    assert row["content_json_filepath"] == str(raw_md)


# ---------------------------------------------------------------------------
# convert_all — success path
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
def test_convert_all_success(tmp_path):
    """All publications converted — content_json_filepath set and cache updated."""
    pubs = [_make_pub(f"10.1037/ca{i}", tmp_path) for i in range(3)]
    output_files = [tmp_path / f"out{i}.md" for i in range(3)]
    for f in output_files:
        f.touch()

    _setup_db([{
        "doi": pub.doi,
        "downloaded_from": "publisher",
        "publication_filepath": str(pub.publication_filepath),
        "content_json_filepath": None,
        "final_md_filepath": None,
    } for pub in pubs])

    call_count = iter(range(3))
    def convert_fn(pub):
        return output_files[next(call_count)]

    cls = _make_converter_class(convert_fn)
    converter = cls(publication_list=pubs)
    converter.cache = TMP_DB
    converter.convert_all()

    for pub, expected_file in zip(pubs, output_files):
        assert pub.content_json_filepath == expected_file
        row = get_row_for_doi(pub.doi, TMP_DB)
        assert row["content_json_filepath"] == str(expected_file)


# ---------------------------------------------------------------------------
# convert_all — None return
# ---------------------------------------------------------------------------
@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
def test_convert_all_skips_on_none_return(tmp_path):
    """Publication whose convert() returns None is skipped; others succeed."""
    pub_fail = _make_pub("10.1037/fail", tmp_path)
    pub_ok = _make_pub("10.1037/ok01", tmp_path)
    out_file = tmp_path / "ok.md"
    out_file.touch()

    _setup_db([
        {"doi": pub_fail.doi, "downloaded_from": "p", "publication_filepath": str(pub_fail.publication_filepath),
         "content_json_filepath": None, "final_md_filepath": None},
        {"doi": pub_ok.doi,   "downloaded_from": "p", "publication_filepath": str(pub_ok.publication_filepath),
         "content_json_filepath": None, "final_md_filepath": None},
    ])

    def convert_fn(pub):
        return None if pub.doi == pub_fail.doi else out_file

    cls = _make_converter_class(convert_fn)
    converter = cls(publication_list=[pub_fail, pub_ok])
    converter.cache = TMP_DB
    converter.convert_all()

    assert pub_fail.content_json_filepath is None
    assert pub_ok.content_json_filepath == out_file

    assert get_row_for_doi(pub_fail.doi, TMP_DB)["content_json_filepath"] is None
    assert get_row_for_doi(pub_ok.doi, TMP_DB)["content_json_filepath"] == str(out_file)


# ---------------------------------------------------------------------------
# convert_all — exception in convert()
# ---------------------------------------------------------------------------
@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
def test_convert_all_skips_on_exception(tmp_path):
    """Exception raised inside convert() is caught; remaining publications still processed."""
    pub_err = _make_pub("10.1037/err1", tmp_path)
    pub_ok = _make_pub("10.1037/ok02", tmp_path)
    out_file = tmp_path / "ok2.md"
    out_file.touch()

    _setup_db([
        {"doi": pub_err.doi, "downloaded_from": "p", "publication_filepath": str(pub_err.publication_filepath),
         "content_json_filepath": None, "final_md_filepath": None},
        {"doi": pub_ok.doi,  "downloaded_from": "p", "publication_filepath": str(pub_ok.publication_filepath),
         "content_json_filepath": None, "final_md_filepath": None},
    ])

    def convert_fn(pub):
        if pub.doi == pub_err.doi:
            raise RuntimeError("Simulated conversion error.")
        return out_file

    cls = _make_converter_class(convert_fn)
    converter = cls(publication_list=[pub_err, pub_ok])
    converter.cache = TMP_DB
    converter.convert_all()

    assert pub_err.content_json_filepath is None
    assert pub_ok.content_json_filepath == out_file