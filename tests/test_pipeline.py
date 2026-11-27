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


def test_load_corpus_build_true_without_scopus_file(tmp_path):
    # A corpus for download_dois() has no Scopus CSV.
    corpus_dir = tmp_path / "doi_corpus"
    assert load_corpus(corpus_dir, build=True) == []

    for subdir in _SUBDIRS:
        assert (corpus_dir / subdir).is_dir()
    assert not (corpus_dir / "scopus.csv").exists()


def test_load_corpus_cached_corpus_without_scopus_csv_returns_empty(tmp_path):
    corpus_dir = tmp_path / "doi_corpus"
    load_corpus(corpus_dir, build=True)
    pdf = corpus_dir / "manuscripts" / "paper.pdf"
    pdf.write_bytes(b"%PDF")
    create_database(corpus_dir / "sqlite.db")
    insert_row(doi="10.1234/a", downloaded_from="opensource", publication_filepath=str(pdf),
               db_path=corpus_dir / "sqlite.db")

    assert load_corpus(corpus_dir) == []


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


# ---------------------------------------------------------------------------
# standardise_text tests
# ---------------------------------------------------------------------------

def test_standardise_text_skips_preflight_when_imrad_off():
    from biomarkit.pipeline import standardise_text
    with patch("biomarkit.standardisation.generics.prepare_standardisation") as mock_preflight, \
            patch("biomarkit.standardisation.text_cleaning.cleaner.Cleaner"):
        standardise_text([], normalise_imrad=False)
    mock_preflight.assert_not_called()


def test_standardise_text_raises_when_imrad_on_and_llm_unavailable():
    from biomarkit.pipeline import standardise_text
    with patch("biomarkit.standardisation.generics.prepare_standardisation", return_value=False), \
            patch("biomarkit.standardisation.text_cleaning.cleaner.Cleaner"):
        with pytest.raises(RuntimeError):
            standardise_text([], normalise_imrad=True)


def test_load_corpus_does_not_import_plotly_or_playwright(tmp_path):
    import subprocess
    import sys
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [{"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021}])
    code = (
        "import sys, biomarkit; "
        f"biomarkit.load_corpus(r'{tmp_path / 'corpus'}', scopus_file=r'{csv}', build=True); "
        "print('plotly' in sys.modules, 'playwright' in sys.modules)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip().splitlines()[-1] == "False False"


def test_load_corpus_warns_and_skips_missing_cached_file(tmp_path, caplog):
    csv = tmp_path / "scopus.csv"
    _write_scopus_csv(csv, [{"doi": "10.1000/aaa", "title": "Paper A", "publisher": "Elsevier", "year": 2021}])
    db = tmp_path / "sqlite.db"
    create_database(db)
    insert_row("10.1000/aaa", "elsevier", str(tmp_path / "manuscripts" / "deleted.pdf"), db)

    with caplog.at_level("WARNING"):
        pubs = load_corpus(tmp_path)

    assert pubs[0].publication_filepath is None
    assert "not found on disk" in caplog.text


# ---------------------------------------------------------------------------
# transform_text routing
# ---------------------------------------------------------------------------

def test_transform_text_routes_bioc_and_elsevier_xmls(tmp_path):
    from biomarkit.pipeline import transform_text
    from biomarkit.text_download.basemodels.publication import Publication

    def _pub(name, doi):
        path = tmp_path / name
        path.write_text("<x/>", encoding="utf-8")
        return Publication(doi=doi, title="t", publisher="p", year=2020, document_type="XML", publication_filepath=path)

    bioc, elsevier = _pub("bioc_1.xml", "10.1234/a"), _pub("elsevier_1.xml", "10.1234/b")

    with patch("biomarkit.text_transformation.controller.controller.Controller.prepare_publications"), \
         patch("biomarkit.text_transformation.controller.controller.Controller.__init__", return_value=None), \
         patch("biomarkit.text_transformation.utils.generics.prepare_bulk_transformation"), \
         patch("biomarkit.text_transformation.utils.generics.finalise_transformation", side_effect=lambda p: p), \
         patch("biomarkit.text_transformation.converters.elsevier2json.ElsevierXmlTransformer") as mock_els, \
         patch("biomarkit.text_transformation.converters.bioc2json.BioCXmlTransformer") as mock_bioc, \
         patch("biomarkit.text_transformation.converters.mineru_pdf_to_md.MinerUPdfTransformer"):
        from biomarkit.text_transformation.controller.controller import Controller
        Controller.needs_transformation = [bioc, elsevier]
        Controller.needs_processing, Controller.completed = [], []
        try:
            transform_text([bioc, elsevier], cleanup_intermediates=False)
        finally:
            del Controller.needs_transformation, Controller.needs_processing, Controller.completed

    assert mock_bioc.call_args.kwargs["publication_list"] == [bioc]
    assert mock_els.call_args.kwargs["publication_list"] == [elsevier]


# ---------------------------------------------------------------------------
# download_dois
# ---------------------------------------------------------------------------

def test_download_dois_routes_crossref_publications_without_scopus_csv(tmp_path):
    import pandas as pd
    from biomarkit.pipeline import download_dois

    load_corpus(tmp_path / "doi_corpus", build=True)
    crossref_df = pd.DataFrame([
        {"Title": "Paper A", "Year": 2020, "DOI": "10.1016/j.a.2020.1", "Publisher": "Elsevier BV", "Abstract": "Abs."},
        {"Title": "Paper B", "Year": 2021, "DOI": "10.3390/b1", "Publisher": "MDPI AG", "Abstract": None},
    ])

    with patch("biomarkit.text_download.filter.crossref_metadata.fetch_crossref_metadata",
               return_value=crossref_df) as mock_fetch, \
         patch("biomarkit.text_download.apis.router.ApiRouter") as mock_router:
        mock_router.return_value.finalise_publication_list.side_effect = lambda results: mock_router.call_args.args[0]
        pubs = download_dois(["10.1016/j.a.2020.1", "https://doi.org/10.3390/b1"])

    mock_fetch.assert_called_once_with(["10.1016/j.a.2020.1", "10.3390/b1"])
    routed = mock_router.call_args.args[0]
    assert [(p.doi, p.publisher, p.year, p.abstract) for p in routed] == [
        ("10.1016/j.a.2020.1", "elsevier", 2020, "Abs."),
        ("10.3390/b1", "mdpi", 2021, None),
    ]
    assert pubs == routed
    assert not (tmp_path / "doi_corpus" / "scopus.csv").exists()


def test_download_dois_raises_when_nothing_resolves(tmp_path):
    import pandas as pd
    from biomarkit.pipeline import download_dois

    load_corpus(tmp_path / "doi_corpus", build=True)
    with patch("biomarkit.text_download.filter.crossref_metadata.fetch_crossref_metadata",
               return_value=pd.DataFrame(columns=["Title", "Year", "DOI", "Publisher", "Abstract"])), \
         patch("biomarkit.text_download.apis.router.ApiRouter") as mock_router:
        with pytest.raises(ValueError, match="could be resolved by Crossref"):
            download_dois(["10.1234/nothing"])
    mock_router.assert_not_called()


def test_download_corpus_still_requires_scopus_csv(tmp_path):
    from biomarkit.pipeline import download_corpus

    load_corpus(tmp_path / "doi_corpus", build=True)
    with pytest.raises(FileNotFoundError, match="download_dois"):
        download_corpus()


def test_standardise_text_rejects_removed_keep_latex():
    from biomarkit.pipeline import standardise_text
    with pytest.raises(TypeError):
        standardise_text([], keep_latex=True, normalise_imrad=False)
