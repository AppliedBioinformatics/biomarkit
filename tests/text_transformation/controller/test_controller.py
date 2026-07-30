import sqlite3
import pytest
import os
from pathlib import Path
from config import TMP_DIR
from text_extraction.basemodels.publication import Publication
from text_extraction.database.database import create_database, insert_row

TMP_DB = TMP_DIR / "tests_tmp" / "test_tt_controller.sqlite"

DB_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT UNIQUE NOT NULL,
    downloaded_from TEXT NOT NULL,
    publication_filepath TEXT NOT NULL,
    raw_md_filepath TEXT,
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
            "(doi, downloaded_from, publication_filepath, raw_md_filepath, final_md_filepath) "
            "VALUES (:doi, :downloaded_from, :publication_filepath, :raw_md_filepath, :final_md_filepath)",
            rows,
        )


def _make_pub(doi: str, tmp_path: Path, publication_filepath: Path = None,
              raw_md_filepath: Path = None, final_md_filepath: Path = None) -> Publication:
    """Builds a Publication object, creating real temp files for any filepath provided."""
    kwargs = dict(doi=doi, title="Test", publisher="TestPublisher", year=2020)
    if publication_filepath:
        publication_filepath.touch()
        kwargs["publication_filepath"] = publication_filepath
    if raw_md_filepath:
        raw_md_filepath.touch()
        kwargs["raw_md_filepath"] = raw_md_filepath
    if final_md_filepath:
        final_md_filepath.touch()
        kwargs["final_md_filepath"] = final_md_filepath
    return Publication(**kwargs)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def uncached_publications():
    """Three publications with no filepaths (not yet downloaded)."""
    return [
        Publication(doi=f"10.1037/tt{i}", title=f"Pub {i}", publisher="Publisher", year=2020)
        for i in range(3)
    ]


@pytest.fixture
def mixed_publications(tmp_path):
    """
    Four publications covering all three sort buckets plus one uncached:
      - pub_a : fully_processed   (all three paths)
      - pub_b : needs_processing  (publication + raw)
      - pub_c : needs_conversion  (publication only)
      - pub_d : uncached          (no paths)
    """
    pub_a = _make_pub(
        "10.1037/tta",
        tmp_path,
        publication_filepath=tmp_path / "a.pdf",
        raw_md_filepath=tmp_path / "a_raw.md",
        final_md_filepath=tmp_path / "a_final.md",
    )
    pub_b = _make_pub(
        "10.1037/ttb",
        tmp_path,
        publication_filepath=tmp_path / "b.pdf",
        raw_md_filepath=tmp_path / "b_raw.md",
    )
    pub_c = _make_pub(
        "10.1037/ttc",
        tmp_path,
        publication_filepath=tmp_path / "c.pdf",
    )
    pub_d = Publication(doi="10.1037/ttd", title="Pub D", publisher="Publisher", year=2020)
    return pub_a, pub_b, pub_c, pub_d


# ---------------------------------------------------------------------------
# _check_cache
# ---------------------------------------------------------------------------

def test_check_cache_creates_db_if_missing(uncached_publications):
    from text_transformation.controller.controller import Controller

    test_db = TMP_DIR / "tests_tmp" / "test_check_cache.sqlite"
    if test_db.exists():
        test_db.unlink()

    controller = Controller(publication_list=uncached_publications)
    controller.cache = test_db
    controller._check_cache()

    assert test_db.exists()


def test_check_cache_does_not_raise_if_db_exists(uncached_publications):
    from text_transformation.controller.controller import Controller

    test_db = TMP_DIR / "tests_tmp" / "test_check_cache.sqlite"
    create_database(test_db)

    controller = Controller(publication_list=uncached_publications)
    controller.cache = test_db
    controller._check_cache()  # Should not raise.


# ---------------------------------------------------------------------------
# _filter_uncached_publications
# ---------------------------------------------------------------------------

def test_filter_uncached_removes_publications_with_no_filepath(mixed_publications):
    from text_transformation.controller.controller import Controller

    pub_a, pub_b, pub_c, pub_d = mixed_publications
    controller = Controller(publication_list=list(mixed_publications))
    controller._filter_uncached_publications()

    assert pub_d not in controller.publications
    assert pub_a in controller.publications
    assert pub_b in controller.publications
    assert pub_c in controller.publications


def test_filter_uncached_all_discarded(uncached_publications):
    from text_transformation.controller.controller import Controller

    controller = Controller(publication_list=uncached_publications)
    controller._filter_uncached_publications()

    assert controller.publications == []


def test_filter_uncached_none_discarded(mixed_publications):
    from text_transformation.controller.controller import Controller

    pub_a, pub_b, pub_c, _ = mixed_publications
    controller = Controller(publication_list=[pub_a, pub_b, pub_c])
    controller._filter_uncached_publications()

    assert len(controller.publications) == 3


# ---------------------------------------------------------------------------
# _update_publications_cache_state
# ---------------------------------------------------------------------------

def test_update_sets_all_three_filepaths(tmp_path, uncached_publications):
    from text_transformation.controller.controller import Controller

    pub = uncached_publications[0]
    doi = pub.doi

    pub_file = tmp_path / "pub.pdf"
    raw_file = tmp_path / "raw.md"
    final_file = tmp_path / "final.md"
    for f in (pub_file, raw_file, final_file):
        f.touch()

    _setup_db([{
        "doi": doi,
        "downloaded_from": "publisher",
        "publication_filepath": str(pub_file),
        "raw_md_filepath": str(raw_file),
        "final_md_filepath": str(final_file),
    }])

    controller = Controller(publication_list=[pub])
    controller.cache = TMP_DB
    controller._update_publications_cache_state()

    assert pub.publication_filepath == pub_file
    assert pub.raw_md_filepath == raw_file
    assert pub.final_md_filepath == final_file

@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
def test_update_sets_only_publication_filepath_when_no_markdown(tmp_path, uncached_publications):
    from text_transformation.controller.controller import Controller

    pub = uncached_publications[0]
    pub_file = tmp_path / "pub.pdf"
    pub_file.touch()

    _setup_db([{
        "doi": pub.doi,
        "downloaded_from": "publisher",
        "publication_filepath": str(pub_file),
        "raw_md_filepath": None,
        "final_md_filepath": None,
    }])

    controller = Controller(publication_list=[pub])
    controller.cache = TMP_DB
    controller._update_publications_cache_state()

    assert pub.publication_filepath == pub_file
    assert pub.raw_md_filepath is None
    assert pub.final_md_filepath is None

@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
def test_update_skips_publication_not_in_cache(uncached_publications):
    from text_transformation.controller.controller import Controller

    _setup_db([])  # Empty DB.
    pub = uncached_publications[0]

    controller = Controller(publication_list=[pub])
    controller.cache = TMP_DB
    controller._update_publications_cache_state()

    assert pub.publication_filepath is None


# ---------------------------------------------------------------------------
# _update_document_types
# ---------------------------------------------------------------------------

def test_update_document_types_sets_xml_for_xml_file(tmp_path):
    from text_transformation.controller.controller import Controller

    xml_file = tmp_path / "paper.xml"
    xml_file.touch()
    pub = _make_pub("10.1037/xml1", tmp_path, publication_filepath=xml_file)

    controller = Controller(publication_list=[pub])
    controller._update_document_types()

    assert pub.document_type == "XML"


def test_update_document_types_leaves_pdf_unchanged(tmp_path):
    from text_transformation.controller.controller import Controller

    pdf_file = tmp_path / "paper.pdf"
    pdf_file.touch()
    pub = _make_pub("10.1037/pdf1", tmp_path, publication_filepath=pdf_file)

    controller = Controller(publication_list=[pub])
    controller._update_document_types()

    assert pub.document_type == "PDF"


# ---------------------------------------------------------------------------
# _sort_publications
# ---------------------------------------------------------------------------

def test_sort_puts_publications_in_correct_lists(mixed_publications):
    from text_transformation.controller.controller import Controller

    pub_a, pub_b, pub_c, _ = mixed_publications
    controller = Controller(publication_list=[pub_a, pub_b, pub_c])
    controller._sort_publications()

    assert pub_a in controller.fully_processed
    assert pub_b in controller.needs_processing
    assert pub_c in controller.needs_conversion


def test_sort_uncached_publication_is_skipped(mixed_publications):
    from text_transformation.controller.controller import Controller

    _, _, _, pub_d = mixed_publications
    controller = Controller(publication_list=[pub_d])
    controller._sort_publications()

    assert pub_d not in controller.fully_processed
    assert pub_d not in controller.needs_processing
    assert pub_d not in controller.needs_conversion


# ---------------------------------------------------------------------------
# prepare_publications (integration)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
def test_prepare_publications_full_pipeline(tmp_path):
    from text_transformation.controller.controller import Controller

    pub_file = tmp_path / "pub.pdf"
    raw_file = tmp_path / "raw.md"
    pub_file.touch()
    raw_file.touch()

    _setup_db([
        {   # needs_processing
            "doi": "10.1037/int1",
            "downloaded_from": "publisher",
            "publication_filepath": str(pub_file),
            "raw_md_filepath": str(raw_file),
            "final_md_filepath": None,
        },
        {   # needs_conversion
            "doi": "10.1037/int2",
            "downloaded_from": "publisher",
            "publication_filepath": str(pub_file),
            "raw_md_filepath": None,
            "final_md_filepath": None,
        },
    ])

    pubs = [
        Publication(doi="10.1037/int1", title="P1", publisher="Pub", year=2020),
        Publication(doi="10.1037/int2", title="P2", publisher="Pub", year=2020),
        Publication(doi="10.1037/int3", title="P3", publisher="Pub", year=2020),  # uncached
    ]

    controller = Controller(publication_list=pubs)
    controller.cache = TMP_DB
    controller.prepare_publications()

    assert len(controller.needs_processing) == 1
    assert len(controller.needs_conversion) == 1
    assert len(controller.fully_processed) == 0
    # Uncached publication must have been discarded.
    assert all(p.doi != "10.1037/int3" for p in controller.publications)