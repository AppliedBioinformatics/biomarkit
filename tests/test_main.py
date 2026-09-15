import pytest
from unittest.mock import patch
from pathlib import Path

from biomarkit.text_download.utils.generics import create_corpus, build_new_corpus
from biomarkit.text_download.database.database import create_database, insert_row, update_content_json_filepath, update_final_md_filepath
from biomarkit.main import load_corpus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCOPUS_HEADER = "Title,Year,DOI,Publisher,Abstract\n"

def _write_scopus_csv(path: Path, rows: list[dict]) -> None:
    lines = _SCOPUS_HEADER
    for r in rows:
        lines += f"{r['title']},{r['year']},{r['doi']},{r['publisher']},{r.get('abstract', 'No abstract.')}\n"
    path.write_text(lines, encoding="utf-8")


# ---------------------------------------------------------------------------
# load_corpus tests
# ---------------------------------------------------------------------------

def test_load_corpus_returns_all_publications_from_csv(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
        {"doi": "10.1000/bbb", "title": "Paper B", "publisher": "Springer", "year": 2022},
    ])

    db = tmp_path / "sqlite.db"
    create_database(db)

    with patch("biomarkit.config.SCOPUS_INPUT_CSV_NAME", csv), \
         patch("biomarkit.config.DB_CACHE_FILE_NAME", db):
        pubs = load_corpus()

    assert len(pubs) == 2
    dois = {p.doi for p in pubs}
    assert "10.1000/aaa" in dois
    assert "10.1000/bbb" in dois


def test_load_corpus_no_filepaths_when_cache_is_empty(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
    ])
    db = tmp_path / "sqlite.db"
    create_database(db)

    with patch("biomarkit.config.SCOPUS_INPUT_CSV_NAME", csv), \
         patch("biomarkit.config.DB_CACHE_FILE_NAME", db):
        pubs = load_corpus()

    assert pubs[0].publication_filepath is None
    assert pubs[0].content_json_filepath is None
    assert pubs[0].final_md_filepath is None


def test_load_corpus_populates_publication_filepath_from_cache(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
    ])
    db = tmp_path / "sqlite.db"
    create_database(db)

    pdf = tmp_path / "manuscripts" / "paper_a.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 %%EOF")

    insert_row("10.1000/aaa", "Elsevier", str(pdf), db)

    with patch("biomarkit.config.SCOPUS_INPUT_CSV_NAME", csv), \
         patch("biomarkit.config.DB_CACHE_FILE_NAME", db):
        pubs = load_corpus()

    assert pubs[0].publication_filepath is not None
    assert Path(pubs[0].publication_filepath).name == "paper_a.pdf"


def test_load_corpus_populates_all_three_filepaths_from_cache(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
    ])
    db = tmp_path / "sqlite.db"
    create_database(db)

    pdf = tmp_path / "manuscripts" / "paper_a.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 %%EOF")

    json_file = tmp_path / "intermediates" / "paper_a.json"
    json_file.parent.mkdir()
    json_file.write_text("{}", encoding="utf-8")

    md_file = tmp_path / "results" / "paper_a.md"
    md_file.parent.mkdir()
    md_file.write_text("# Paper A", encoding="utf-8")

    insert_row("10.1000/aaa", "Elsevier", str(pdf), db)
    update_content_json_filepath("10.1000/aaa", str(json_file), db)
    update_final_md_filepath("10.1000/aaa", str(md_file), db)

    with patch("biomarkit.config.SCOPUS_INPUT_CSV_NAME", csv), \
         patch("biomarkit.config.DB_CACHE_FILE_NAME", db):
        pubs = load_corpus()

    pub = pubs[0]
    assert pub.is_cached
    assert pub.is_converted
    assert pub.is_processed


def test_load_corpus_partial_cache_hit(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
        {"doi": "10.1000/bbb", "title": "Paper B", "publisher": "Springer", "year": 2022},
    ])
    db = tmp_path / "sqlite.db"
    create_database(db)

    pdf = tmp_path / "manuscripts" / "paper_a.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 %%EOF")
    insert_row("10.1000/aaa", "Elsevier", str(pdf), db)

    with patch("biomarkit.config.SCOPUS_INPUT_CSV_NAME", csv), \
         patch("biomarkit.config.DB_CACHE_FILE_NAME", db):
        pubs = load_corpus()

    assert len(pubs) == 2
    cached = next(p for p in pubs if p.doi == "10.1000/aaa")
    uncached = next(p for p in pubs if p.doi == "10.1000/bbb")
    assert cached.is_cached
    assert not uncached.is_cached


def test_load_corpus_no_cache_file(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
    ])
    db = tmp_path / "sqlite.db"  # intentionally not created

    with patch("biomarkit.config.SCOPUS_INPUT_CSV_NAME", csv), \
         patch("biomarkit.config.DB_CACHE_FILE_NAME", db):
        pubs = load_corpus()

    assert len(pubs) == 1
    assert pubs[0].publication_filepath is None


def test_load_corpus_preserves_metadata_from_csv(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Effects of X on Y", "publisher": "Elsevier", "year": 2019, "abstract": "Some abstract."},
    ])
    db = tmp_path / "sqlite.db"
    create_database(db)

    with patch("biomarkit.config.SCOPUS_INPUT_CSV_NAME", csv), \
         patch("biomarkit.config.DB_CACHE_FILE_NAME", db):
        pubs = load_corpus()

    pub = pubs[0]
    assert pub.title == "Effects of X on Y"
    assert pub.year == 2019
    assert pub.abstract == "Some abstract."


def test_create_corpus_builds_folder_structure(tmp_path):
    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        corpus_dir = create_corpus("my_corpus")

    assert corpus_dir == tmp_path / "my_corpus"
    for subdir in ("manuscripts", "intermediates", "results", "reports", "logs"):
        assert (corpus_dir / subdir).is_dir()


def test_create_corpus_is_idempotent(tmp_path):
    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        first = create_corpus("my_corpus")
        marker = first / "manuscripts" / "existing.pdf"
        marker.touch()

        second = create_corpus("my_corpus")

    assert first == second
    assert marker.exists()


def test_create_corpus_strips_whitespace(tmp_path):
    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        corpus_dir = create_corpus("  my_corpus  ")

    assert corpus_dir == tmp_path / "my_corpus"


@pytest.mark.parametrize("bad_name", ["", "   ", "a/b", "a\\b", "bad:name", "bad|name"])
def test_create_corpus_rejects_invalid_names(bad_name, tmp_path):
    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        with pytest.raises(ValueError, match="Invalid corpus name"):
            create_corpus(bad_name)


# --- build_new_corpus ---

def test_build_new_corpus_creates_structure_and_copies_csv(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("doi,title\n10.1/x,Paper X")

    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        corpus_dir = build_new_corpus(name="test_corpus", scopus_file=scopus_csv, set_active=False)

    assert corpus_dir == tmp_path / "test_corpus"
    for subdir in ("manuscripts", "intermediates", "results", "reports", "logs"):
        assert (corpus_dir / subdir).is_dir()
    assert (corpus_dir / "scopus.csv").read_text() == "doi,title\n10.1/x,Paper X"


def test_build_new_corpus_raises_if_scopus_missing(tmp_path):
    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        with pytest.raises(FileNotFoundError, match="Scopus CSV not found"):
            build_new_corpus(name="test_corpus", scopus_file=tmp_path / "missing.csv", set_active=False)


def test_build_new_corpus_does_not_overwrite_existing_csv(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("new content")

    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        corpus_dir = build_new_corpus(name="test_corpus", scopus_file=scopus_csv, set_active=False)
        existing = corpus_dir / "scopus.csv"
        existing.write_text("original content")

        build_new_corpus(name="test_corpus", scopus_file=scopus_csv, set_active=False)

    assert existing.read_text() == "original content"


def test_build_new_corpus_set_active_updates_existing_secrets_env(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("doi,title")
    secrets = tmp_path / "secrets.env"
    secrets.write_text("CORPUS_NAME=old_corpus\nUSER_EMAIL=x@x.com\n")

    with patch("biomarkit.config.CORPORA_DIR", tmp_path), \
         patch("biomarkit.text_download.utils.generics._secrets_path", return_value=secrets):
        build_new_corpus(name="new_corpus", scopus_file=scopus_csv, set_active=True)

    updated = secrets.read_text(encoding="utf-8")
    assert "CORPUS_NAME=new_corpus" in updated
    assert "USER_EMAIL=x@x.com" in updated


def test_build_new_corpus_set_active_creates_secrets_env_if_absent(tmp_path):
    scopus_csv = tmp_path / "scopus.csv"
    scopus_csv.write_text("doi,title")
    secrets = tmp_path / "secrets.env"

    with patch("biomarkit.config.CORPORA_DIR", tmp_path), \
         patch("biomarkit.text_download.utils.generics._secrets_path", return_value=secrets):
        build_new_corpus(name="fresh_corpus", scopus_file=scopus_csv, set_active=True)

    assert "CORPUS_NAME=fresh_corpus" in secrets.read_text(encoding="utf-8")