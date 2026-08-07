import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from text_download.utils.generics import (
    clean_publications,
    truncate_labels,
    validate_pdf_file,
    validate_xml_file,
    validate_publications,
)
from text_download.basemodels.publication import Publication, DocumentType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE cache (id INTEGER PRIMARY KEY, doi TEXT NOT NULL, "
        "downloaded_from TEXT NOT NULL, publication_filepath TEXT NOT NULL, "
        "content_json_filepath TEXT, final_md_filepath TEXT)"
    )
    conn.commit()
    conn.close()


def _insert(db: Path, filepath: str) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO cache (doi, downloaded_from, publication_filepath) VALUES (?,?,?)",
        ("10.1000/x", "test", filepath),
    )
    conn.commit()
    conn.close()


def _make_pub(doi="10.1000/x", doc_type=DocumentType.PDF, filepath=None) -> Publication:
    return Publication(doi=doi, title="T", publisher="P", year=2020,
                       document_type=doc_type, publication_filepath=filepath)


# ---------------------------------------------------------------------------
# truncate_labels
# ---------------------------------------------------------------------------

def test_truncate_labels_short_string_unchanged():
    assert truncate_labels("short") == "short"


def test_truncate_labels_exactly_50_unchanged():
    s = "a" * 50
    assert truncate_labels(s) == s


def test_truncate_labels_51_chars_truncated():
    s = "a" * 51
    result = truncate_labels(s)
    assert result.endswith("…")
    assert result == "a" * 47 + "…"


# ---------------------------------------------------------------------------
# validate_pdf_file
# ---------------------------------------------------------------------------

def test_validate_pdf_file_valid(tmp_path):
    f = tmp_path / "ok.pdf"
    f.write_bytes(b"%PDF-1.4 some content %%EOF")
    assert validate_pdf_file(f) is True


def test_validate_pdf_file_missing_header(tmp_path):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a pdf %%EOF")
    assert validate_pdf_file(f) is False


def test_validate_pdf_file_missing_eof(tmp_path):
    f = tmp_path / "noeof.pdf"
    f.write_bytes(b"%PDF-1.4 content without eof marker")
    assert validate_pdf_file(f) is False


def test_validate_pdf_file_empty(tmp_path):
    f = tmp_path / "empty.pdf"
    f.write_bytes(b"")
    assert validate_pdf_file(f) is False


def test_validate_pdf_file_nonexistent(tmp_path):
    assert validate_pdf_file(tmp_path / "missing.pdf") is False


# ---------------------------------------------------------------------------
# validate_xml_file
# ---------------------------------------------------------------------------

def test_validate_xml_file_valid(tmp_path):
    f = tmp_path / "ok.xml"
    f.write_text("<root><child>text</child></root>", encoding="utf-8")
    assert validate_xml_file(f) is True


def test_validate_xml_file_malformed(tmp_path):
    f = tmp_path / "bad.xml"
    f.write_text("<root><unclosed>", encoding="utf-8")
    assert validate_xml_file(f) is False


def test_validate_xml_file_not_xml(tmp_path):
    f = tmp_path / "notxml.xml"
    f.write_text("just plain text, no tags", encoding="utf-8")
    assert validate_xml_file(f) is False


def test_validate_xml_file_empty(tmp_path):
    f = tmp_path / "empty.xml"
    f.write_bytes(b"")
    assert validate_xml_file(f) is False


def test_validate_xml_file_with_bom(tmp_path):
    f = tmp_path / "bom.xml"
    f.write_bytes(b"\xef\xbb\xbf<root/>")
    assert validate_xml_file(f) is True


def test_validate_xml_file_nonexistent(tmp_path):
    assert validate_xml_file(tmp_path / "missing.xml") is False


# ---------------------------------------------------------------------------
# clean_publications
# ---------------------------------------------------------------------------

def test_clean_publications_removes_untracked_file(tmp_path):
    db = tmp_path / "cache.db"
    _make_db(db)
    folder = tmp_path / "downloads"
    folder.mkdir()
    orphan = folder / "orphan.pdf"
    orphan.write_bytes(b"%PDF")
    clean_publications(folder=folder, db_path=db)
    assert not orphan.exists()


def test_clean_publications_keeps_tracked_file(tmp_path):
    db = tmp_path / "cache.db"
    _make_db(db)
    folder = tmp_path / "downloads"
    folder.mkdir()
    tracked = folder / "tracked.pdf"
    tracked.write_bytes(b"%PDF")
    _insert(db, str(tracked))
    clean_publications(folder=folder, db_path=db)
    assert tracked.exists()


def test_clean_publications_empty_folder_no_error(tmp_path):
    db = tmp_path / "cache.db"
    _make_db(db)
    folder = tmp_path / "downloads"
    folder.mkdir()
    clean_publications(folder=folder, db_path=db)


# ---------------------------------------------------------------------------
# validate_publications
# ---------------------------------------------------------------------------

def test_validate_publications_valid_pdf(tmp_path):
    f = tmp_path / "paper.pdf"
    f.write_bytes(b"%PDF-1.4 content %%EOF")
    pub = _make_pub(filepath=f)
    stats = validate_publications([pub])
    assert stats["PDF"]["valid"] == 1
    assert stats["PDF"]["invalid"] == 0


def test_validate_publications_invalid_pdf(tmp_path):
    f = tmp_path / "bad.pdf"
    f.write_bytes(b"not a pdf")
    pub = _make_pub(filepath=f)
    stats = validate_publications([pub])
    assert stats["PDF"]["invalid"] == 1


def test_validate_publications_missing_filepath():
    pub = _make_pub(filepath=None)
    stats = validate_publications([pub])
    assert stats["PDF"]["missing_path"] == 1


def test_validate_publications_valid_xml(tmp_path):
    f = tmp_path / "paper.xml"
    f.write_text("<root/>", encoding="utf-8")
    pub = _make_pub(doc_type=DocumentType.XML, filepath=f)
    stats = validate_publications([pub])
    assert stats["XML"]["valid"] == 1


def test_validate_publications_empty_list():
    stats = validate_publications([])
    assert stats == {}