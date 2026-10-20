import pytest
from unittest.mock import patch
from pathlib import Path

from biomarkit.text_download.database.database import create_database, insert_row, update_content_json_filepath, update_final_md_filepath
from biomarkit import config
from biomarkit.pipeline import load_corpus


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

    pdf_a = tmp_path / "manuscripts" / "paper_a.pdf"
    pdf_a.parent.mkdir()
    pdf_a.write_bytes(b"%PDF-1.4 %%EOF")
    pdf_b = tmp_path / "manuscripts" / "paper_b.pdf"
    pdf_b.write_bytes(b"%PDF-1.4 %%EOF")
    insert_row("10.1000/aaa", "elsevier", str(pdf_a), db)
    insert_row("10.1000/bbb", "springer", str(pdf_b), db)

    pubs = load_corpus(tmp_path)

    assert len(pubs) == 2
    dois = {p.doi for p in pubs}
    assert "10.1000/aaa" in dois
    assert "10.1000/bbb" in dois


def test_load_corpus_no_json_or_md_filepath_when_not_yet_converted(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
    ])
    db = tmp_path / "sqlite.db"
    create_database(db)

    pdf = tmp_path / "manuscripts" / "paper_a.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 %%EOF")
    insert_row("10.1000/aaa", "elsevier", str(pdf), db)

    pubs = load_corpus(tmp_path)

    assert pubs[0].publication_filepath is not None
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

    pubs = load_corpus(tmp_path)

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

    pubs = load_corpus(tmp_path)

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

    pubs = load_corpus(tmp_path)

    assert len(pubs) == 1
    assert pubs[0].doi == "10.1000/aaa"
    assert pubs[0].is_cached


def test_load_corpus_no_cache_file(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021},
    ])
    db = tmp_path / "sqlite.db"  # intentionally not created

    pubs = load_corpus(tmp_path)

    assert len(pubs) == 0


def test_load_corpus_preserves_metadata_from_csv(tmp_path):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [
        {"doi": "10.1000/aaa", "title": "Effects of X on Y", "publisher": "Elsevier", "year": 2019, "abstract": "Some abstract."},
    ])
    db = tmp_path / "sqlite.db"
    create_database(db)

    pdf = tmp_path / "manuscripts" / "paper_a.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF-1.4 %%EOF")
    insert_row("10.1000/aaa", "elsevier", str(pdf), db)

    pubs = load_corpus(tmp_path)

    pub = pubs[0]
    assert pub.title == "Effects of X on Y"
    assert pub.year == 2019
    assert pub.abstract == "Some abstract."


# ---------------------------------------------------------------------------
# load_corpus — corpus selection and building
# ---------------------------------------------------------------------------

_SUBDIRS = ("manuscripts", "intermediates", "results", "reports", "logs")


@pytest.fixture
def scopus_src(tmp_path):
    src = tmp_path / "src" / "my_export.csv"
    src.parent.mkdir()
    _write_scopus_csv(src, [{"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021}])
    return src


def test_load_corpus_sets_active_corpus(tmp_path):
    load_corpus(tmp_path)
    assert config.get_corpus().root == tmp_path.resolve()


def test_load_corpus_resolves_name_under_corpora_dir(tmp_path):
    (tmp_path / "my_corpus").mkdir()
    with patch("biomarkit.config.CORPORA_DIR", tmp_path):
        load_corpus("my_corpus")
    assert config.get_corpus().root == (tmp_path / "my_corpus").resolve()


def test_load_corpus_switching_changes_output_folders(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    load_corpus(a)
    assert config.get_corpus().final_md_dir == a.resolve() / "results"
    load_corpus(b)
    assert config.get_corpus().final_md_dir == b.resolve() / "results"


def test_pipeline_function_before_load_corpus_raises():
    from biomarkit.pipeline import download_corpus
    config._active_corpus = None
    with pytest.raises(RuntimeError, match="No corpus loaded"):
        download_corpus()


def test_load_corpus_build_true_creates_structure_and_copies_csv(tmp_path, scopus_src):
    corpus_dir = tmp_path / "new_corpus"
    pubs = load_corpus(corpus_dir, scopus_file=scopus_src, build=True)

    assert pubs == []
    for subdir in _SUBDIRS:
        assert (corpus_dir / subdir).is_dir()
    assert (corpus_dir / "scopus.csv").read_text(encoding="utf-8") == scopus_src.read_text(encoding="utf-8")
    assert config.get_corpus().root == corpus_dir.resolve()


def test_load_corpus_build_false_raises_when_missing(tmp_path, scopus_src):
    with pytest.raises(FileNotFoundError, match="Corpus not found"):
        load_corpus(tmp_path / "missing", scopus_file=scopus_src, build=False)
    assert not (tmp_path / "missing").exists()


def test_load_corpus_missing_without_scopus_file_raises_before_prompt(tmp_path):
    with patch("biomarkit.pipeline._can_prompt", return_value=True), \
         patch("builtins.input") as mock_input:
        with pytest.raises(ValueError, match="scopus_file"):
            load_corpus(tmp_path / "missing")
    mock_input.assert_not_called()


def test_load_corpus_raises_if_scopus_file_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="Scopus CSV not found"):
        load_corpus(tmp_path / "new_corpus", scopus_file=tmp_path / "missing.csv", build=True)


@pytest.mark.parametrize("answer", ["y", "Y", "yes", " yes "])
def test_load_corpus_prompt_yes_builds(tmp_path, scopus_src, answer):
    corpus_dir = tmp_path / "new_corpus"
    with patch("biomarkit.pipeline._can_prompt", return_value=True), \
         patch("builtins.input", return_value=answer):
        load_corpus(corpus_dir, scopus_file=scopus_src)
    assert (corpus_dir / "scopus.csv").exists()


@pytest.mark.parametrize("answer", ["n", "", "no", "maybe"])
def test_load_corpus_prompt_no_raises(tmp_path, scopus_src, answer):
    corpus_dir = tmp_path / "new_corpus"
    with patch("biomarkit.pipeline._can_prompt", return_value=True), \
         patch("builtins.input", return_value=answer):
        with pytest.raises(FileNotFoundError, match="Corpus not built"):
            load_corpus(corpus_dir, scopus_file=scopus_src)
    assert not corpus_dir.exists()


def test_load_corpus_non_interactive_raises_without_prompting(tmp_path, scopus_src):
    with patch("biomarkit.pipeline._can_prompt", return_value=False), \
         patch("builtins.input") as mock_input:
        with pytest.raises(FileNotFoundError, match="build=True"):
            load_corpus(tmp_path / "new_corpus", scopus_file=scopus_src)
    mock_input.assert_not_called()


def test_load_corpus_prompt_eof_raises_build_hint(tmp_path, scopus_src):
    with patch("biomarkit.pipeline._can_prompt", return_value=True), \
         patch("builtins.input", side_effect=EOFError):
        with pytest.raises(FileNotFoundError, match="build=True"):
            load_corpus(tmp_path / "new_corpus", scopus_file=scopus_src)
    assert not (tmp_path / "new_corpus").exists()


def test_load_corpus_existing_corpus_does_not_prompt(tmp_path):
    with patch("builtins.input") as mock_input:
        load_corpus(tmp_path)
    mock_input.assert_not_called()


def test_load_corpus_does_not_overwrite_existing_scopus_csv(tmp_path, scopus_src):
    (tmp_path / "scopus.csv").write_text("original content", encoding="utf-8")
    load_corpus(tmp_path, scopus_file=scopus_src)
    assert (tmp_path / "scopus.csv").read_text(encoding="utf-8") == "original content"


def test_load_corpus_copies_scopus_csv_into_existing_corpus_without_one(tmp_path, scopus_src):
    corpus_dir = tmp_path / "existing"
    corpus_dir.mkdir()
    load_corpus(corpus_dir, scopus_file=scopus_src)
    assert (corpus_dir / "scopus.csv").exists()


@pytest.mark.parametrize("bad_name", ["", "   ", "bad:name", "bad|name", "bad*name"])
def test_load_corpus_rejects_invalid_names(bad_name):
    with pytest.raises(ValueError, match="Invalid corpus name"):
        load_corpus(bad_name, build=False)


def test_load_corpus_does_not_touch_secrets_env(tmp_path, scopus_src, monkeypatch):
    monkeypatch.chdir(tmp_path)
    load_corpus(tmp_path / "new_corpus", scopus_file=scopus_src, build=True)
    assert not (tmp_path / "secrets.env").exists()
