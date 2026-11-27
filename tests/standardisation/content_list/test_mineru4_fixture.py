"""
Guards Stage 3 against MinerU output-format drift, using real MinerU 4.0.12 Content List V2 output
(one block of each type taken from corpus PDFs, plus a paragraph with hyperlink spans).
"""
import json
import shutil
from pathlib import Path

from biomarkit.standardisation.content_list.schema import Document, MiscBlock
from biomarkit.standardisation.content_list.renderer import render
from biomarkit.text_download.basemodels.publication import Publication

FIXTURE = Path(__file__).parent.parent / "fixtures" / "mineru4_content_list_v2.json"


def test_fixture_parses_into_known_block_types_only():
    doc = Document.from_file(FIXTURE)
    types = {b.type for b in doc.blocks()}
    assert {"title", "paragraph", "image", "chart", "table", "list", "equation_interline"} <= types
    assert not [b for b in doc.blocks() if isinstance(b, MiscBlock)]


def test_hyperlink_spans_render_as_their_text():
    doc = Document.from_file(FIXTURE)
    markdown = render(doc.pages[1])
    assert "supplementary material available at https://doi.org/10.1186/s12915-" in markdown
    assert "02081-y" in markdown


def test_cleaner_produces_markdown_from_fixture(tmp_path, active_corpus):
    from biomarkit.standardisation.text_cleaning.cleaner import Cleaner

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 %%EOF")
    json_path = tmp_path / "paper" / "auto" / "paper_content_list_v2.json"
    json_path.parent.mkdir(parents=True)
    shutil.copy(FIXTURE, json_path)
    pub = Publication(doi="10.1000/test.mineru4", title="t", publisher="t", year=2026,
                      publication_filepath=pdf, content_json_filepath=json_path)

    cleaner = Cleaner(publications=[], cache=None, context=dict(
        keep_figures=True, keep_tables=True, keep_latex=True, keep_references=True, keep_boilerplate=False,
        normalise_imrad=False))
    markdown = cleaner.clean_from_json(pub)

    assert markdown.startswith("#")
    assert "<table" in markdown
    assert "](" in markdown  # image/chart links
    assert "$$\nG = \\frac {\\mathsf {Z Z ^ {\\prime}}}{\\sum p (1 - p)}\n$$" in markdown  # display equation
    assert pub.final_md_filepath == active_corpus.final_md_dir / "paper.md"


def test_keep_boilerplate_controls_page_furniture(tmp_path, active_corpus):
    from biomarkit.standardisation.text_cleaning.cleaner import Cleaner

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 %%EOF")
    json_path = tmp_path / "paper" / "auto" / "paper_content_list_v2.json"
    json_path.parent.mkdir(parents=True)
    shutil.copy(FIXTURE, json_path)
    pub = Publication(doi="10.1000/test.boilerplate", title="t", publisher="t", year=2026,
                      publication_filepath=pdf, content_json_filepath=json_path)
    base = dict(keep_figures=True, keep_tables=True, keep_latex=True, keep_references=True, normalise_imrad=False)

    kept = Cleaner(publications=[], cache=None, context={**base, "keep_boilerplate": True}).clean_from_json(pub)
    removed = Cleaner(publications=[], cache=None, context={**base, "keep_boilerplate": False}).clean_from_json(pub)

    for text in ("*Correspondence:", "Page 2 of 24"):
        assert text in kept
        assert text not in removed
