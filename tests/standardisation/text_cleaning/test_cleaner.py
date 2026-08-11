import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from standardisation.content_list.schema import (
    ImageSource, ImageContent, ImageBlock,
    ParagraphBlock, ParagraphContent,
    TextSpan, TitleBlock, TitleContent,
)
from standardisation.text_cleaning.cleaner import Cleaner
from text_download.basemodels.publication import Publication

_BBOX = (0, 0, 0, 0)


def make_paragraph(text: str) -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph",
        content=ParagraphContent(paragraph_content=[TextSpan(type="text", content=text)]),
        bbox=_BBOX,
    )


def make_title(text: str, level: int = 1) -> TitleBlock:
    return TitleBlock(
        type="title",
        content=TitleContent(title_content=[TextSpan(type="text", content=text)], level=level),
        bbox=_BBOX,
    )


def make_cleaner(**ctx_overrides) -> Cleaner:
    context = dict(
        keep_figures=False, keep_tables=False, keep_latex=False,
        keep_references=False, force_imrad_structure=False,
    )
    context.update(ctx_overrides)
    return Cleaner(publications=[], context=context, cache=None)


# ---------------------------------------------------------------------------
# _normalise_heading
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    # Plain words (no numeric prefix) — returned lowercased as-is.
    ("Methods", "methods"),
    ("Discussion", "discussion"),
    ("Results", "results"),
    ("Background", "background"),
    # Numeric / symbol prefixes are stripped.
    ("II. Methods", "methods"),
    ("§3 Results", "results"),
    ("  Discussion  ", "discussion"),
    ("1.2.3 Background", "background"),
    ("1. Methods", "methods"),
])
def test_normalise_heading(text, expected):
    block = make_title(text)
    assert Cleaner._normalise_heading(block) == expected


# ---------------------------------------------------------------------------
# Section detectors
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Background", "background", "1. Background"])
def test_is_intro_heading_matches(text):
    assert Cleaner._is_intro_heading(make_title(text))


@pytest.mark.parametrize("text", ["Methods", "Results", "Discussion", "Abstract"])
def test_is_intro_heading_no_match(text):
    assert not Cleaner._is_intro_heading(make_title(text))


@pytest.mark.parametrize("text", [
    "Methods", "Materials and Methods", "Materials & Methods",
    "Methodology", "Experimental Section", "Patients and Methods", "Study Design",
])
def test_is_methods_heading_matches(text):
    assert Cleaner._is_methods_heading(make_title(text))


@pytest.mark.parametrize("text", ["Results", "Introduction", "Discussion"])
def test_is_methods_heading_no_match(text):
    assert not Cleaner._is_methods_heading(make_title(text))


@pytest.mark.parametrize("text", ["Results", "Findings", "Outcomes", "2. Results"])
def test_is_results_heading_matches(text):
    assert Cleaner._is_results_heading(make_title(text))


def test_is_results_and_discussion_heading_matches():
    assert Cleaner._is_results_and_discussion_heading(make_title("Results and Discussion"))
    assert Cleaner._is_results_and_discussion_heading(make_title("Results & Discussion"))


def test_is_results_and_discussion_heading_no_match():
    assert not Cleaner._is_results_and_discussion_heading(make_title("Results"))


@pytest.mark.parametrize("text", [
    "Discussion", "Conclusions and Discussion", "Discussion and Conclusions",
])
def test_is_discussion_heading_matches(text):
    assert Cleaner._is_discussion_heading(make_title(text))


# ---------------------------------------------------------------------------
# _rename_heading
# ---------------------------------------------------------------------------

def test_rename_heading_mutates_block():
    block = make_title("Old Name")
    Cleaner._rename_heading(block, "New Name")
    assert block.content.title_content[0].content == "New Name"
    assert block.content.title_content[0].type == "text"


# ---------------------------------------------------------------------------
# _insert_intro_heading
# ---------------------------------------------------------------------------

def test_insert_intro_heading_renames_existing_title_block():
    blocks = [make_title("Introduction stuff", level=1)]
    result = Cleaner._insert_intro_heading(blocks, 0)
    assert result[0].content.title_content[0].content == "Introduction"
    assert len(result) == 1


def test_insert_intro_heading_inserts_before_non_title_block():
    para = make_paragraph("First paragraph")
    blocks = [para]
    result = Cleaner._insert_intro_heading(blocks, 0)
    assert len(result) == 2
    assert result[0].type == "title"
    assert result[0].content.title_content[0].content == "Introduction"
    assert result[1] is para


# ---------------------------------------------------------------------------
# _insert_end_marker
# ---------------------------------------------------------------------------

def test_insert_end_marker_renames_existing_title_block():
    blocks = [make_title("References")]
    result = Cleaner._insert_end_marker(blocks, 0)
    assert result[0].content.title_content[0].content == "end"
    assert len(result) == 1


def test_insert_end_marker_inserts_before_non_title():
    para = make_paragraph("ref text")
    blocks = [para]
    result = Cleaner._insert_end_marker(blocks, 0)
    assert len(result) == 2
    assert result[0].content.title_content[0].content == "end"


# ---------------------------------------------------------------------------
# _trim_to_core_text
# ---------------------------------------------------------------------------

def test_trim_to_core_text_slices_between_markers():
    blocks = [
        make_paragraph("before intro"),
        make_title("Introduction"),
        make_paragraph("body"),
        make_title("end"),
        make_paragraph("after"),
    ]
    result = Cleaner._trim_to_core_text(blocks)
    texts = [b.content.paragraph_content[0].content if b.type == "paragraph"
             else b.content.title_content[0].content for b in result]
    assert "before intro" not in texts
    assert "after" not in texts
    assert "Introduction" in texts
    assert "body" in texts


def test_trim_to_core_text_no_intro_starts_from_zero():
    blocks = [make_paragraph("body"), make_title("end"), make_paragraph("after")]
    result = Cleaner._trim_to_core_text(blocks)
    assert result[0].content.paragraph_content[0].content == "body"
    assert len(result) == 1  # up to (not including) "end"


def test_trim_to_core_text_no_end_goes_to_finish():
    blocks = [make_title("Introduction"), make_paragraph("body")]
    result = Cleaner._trim_to_core_text(blocks)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# _build_llm_context
# ---------------------------------------------------------------------------

def test_build_llm_context_headings_and_paragraphs():
    blocks = [make_title("Introduction"), make_paragraph("A" * 60)]
    ctx = Cleaner._build_llm_context(blocks)
    assert ctx[0] == "[heading] Introduction"
    assert ctx[1].startswith("[paragraph] ")
    assert len(ctx[1]) <= len("[paragraph] ") + 50


def test_build_llm_context_indexes_match_position():
    blocks = [make_paragraph(f"p{i}") for i in range(5)]
    ctx = Cleaner._build_llm_context(blocks)
    assert list(ctx.keys()) == list(range(5))


# ---------------------------------------------------------------------------
# _build_headings_context
# ---------------------------------------------------------------------------

def test_build_headings_context_only_includes_titles():
    blocks = [make_title("Methods"), make_paragraph("body"), make_title("Results")]
    ctx = Cleaner._build_headings_context(blocks)
    assert len(ctx) == 2
    assert all(v.startswith("[heading]") for v in ctx.values())


# ---------------------------------------------------------------------------
# _find_introduction_start — regex path (no LLM call)
# ---------------------------------------------------------------------------

def test_find_introduction_start_regex_path():
    cleaner = make_cleaner()
    # "Background" starts with B — not affected by the Roman numeral prefix strip.
    blocks = [make_paragraph("abstract"), make_title("Background")]
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier") as mock_llm:
        result = cleaner._find_introduction_start(blocks)
    mock_llm.assert_not_called()
    intro = next(b for b in result if b.type == "title")
    assert intro.content.title_content[0].content == "Introduction"


def test_find_introduction_start_picks_highest_level_heading():
    cleaner = make_cleaner()
    # Level 1 "Introduction" and level 2 "Introduction" both match — level 1 wins, level 2 is dropped.
    blocks = [make_title("Introduction", level=1), make_title("Introduction", level=2)]
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier"):
        result = cleaner._find_introduction_start(blocks)
    title_blocks = [b for b in result if b.type == "title"]
    assert len(title_blocks) == 1
    assert title_blocks[0].content.level == 1


def test_find_introduction_start_drops_lower_level_duplicate():
    cleaner = make_cleaner()
    # Simulates "# Introduction" inserted by cleaner + "## 1 Introduction" from the article.
    para = make_paragraph("body text")
    blocks = [make_title("Introduction", level=1), make_title("1 Introduction", level=2), para]
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier"):
        result = cleaner._find_introduction_start(blocks)
    title_blocks = [b for b in result if b.type == "title"]
    assert len(title_blocks) == 1
    assert title_blocks[0].content.title_content[0].content == "Introduction"


# ---------------------------------------------------------------------------
# _find_introduction_start — LLM fallback path
# ---------------------------------------------------------------------------

def test_find_introduction_start_llm_fallback():
    cleaner = make_cleaner()
    blocks = [make_paragraph("abstract text"), make_paragraph("more text")]
    mock_instance = MagicMock()
    mock_instance.classify_intro.return_value = 0
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        result = cleaner._find_introduction_start(blocks)
    mock_instance.classify_intro.assert_called_once()
    assert result[0].type == "title"
    assert result[0].content.title_content[0].content == "Introduction"


def test_find_introduction_start_llm_returns_none(caplog):
    cleaner = make_cleaner()
    blocks = [make_paragraph("text")]
    mock_instance = MagicMock()
    mock_instance.classify_intro.return_value = None
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        with caplog.at_level("WARNING"):
            result = cleaner._find_introduction_start(blocks)
    assert result == blocks
    assert "LLM could not identify introduction" in caplog.text


# ---------------------------------------------------------------------------
# _enforce_imrad_headings — regex finds all sections, no LLM
# ---------------------------------------------------------------------------

def test_enforce_imrad_headings_regex_path_no_llm():
    cleaner = make_cleaner()
    blocks = [
        make_title("Introduction"),
        make_title("Methods"),
        make_title("Results"),
        make_title("Discussion"),
    ]
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier") as mock_llm:
        cleaner._enforce_imrad_headings(blocks)
    mock_llm.assert_not_called()


def test_enforce_imrad_headings_renames_methods_via_llm():
    cleaner = make_cleaner()
    methods_block = make_title("Experimental")
    blocks = [make_title("Introduction"), methods_block, make_title("Results")]
    mock_instance = MagicMock()
    mock_instance.classify_methods.return_value = 1
    mock_instance.classify_results.return_value = None
    mock_instance.classify_discussion.return_value = None
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        cleaner._enforce_imrad_headings(blocks)
    assert blocks[1].content.title_content[0].content == "Methods"


def test_enforce_imrad_headings_discussion_optional_no_warning(caplog):
    cleaner = make_cleaner()
    blocks = [make_title("Introduction"), make_title("Methods"), make_title("Results")]
    mock_instance = MagicMock()
    mock_instance.classify_methods.return_value = None
    mock_instance.classify_results.return_value = None
    mock_instance.classify_discussion.return_value = None
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        with caplog.at_level("WARNING"):
            cleaner._enforce_imrad_headings(blocks)
    assert "Discussion" not in caplog.text


# ---------------------------------------------------------------------------
# clean_from_json — integration (filesystem patched, no LLM)
# ---------------------------------------------------------------------------

# Document.from_file expects a raw list[list[dict]] — pages of blocks.
_MINIMAL_CONTENT_LIST = [
    [
        {
            "type": "title",
            "bbox": [0, 0, 0, 0],
            "content": {
                "title_content": [{"type": "text", "content": "Background"}],
                "level": 1,
            },
        },
        {
            "type": "paragraph",
            "bbox": [0, 0, 0, 0],
            "content": {
                "paragraph_content": [{"type": "text", "content": "Body text here."}],
            },
        },
    ]
]


def _write_pub(tmp_path: Path) -> Publication:
    pdf = tmp_path / "paper_abc123.pdf"
    pdf.write_bytes(b"%PDF-1.4 %%EOF")
    json_dir = tmp_path / "paper_abc123" / "auto"
    json_dir.mkdir(parents=True)
    json_file = json_dir / "paper_abc123_content_list_v2.json"
    json_file.write_text(json.dumps(_MINIMAL_CONTENT_LIST), encoding="utf-8")
    return Publication(
        doi="10.1016/j.test.2020.01.001",
        title="Test",
        publisher="Test",
        year=2020,
        publication_filepath=pdf,
        content_json_filepath=json_file,
    )


def test_clean_from_json_writes_markdown_file(tmp_path):
    pub = _write_pub(tmp_path)
    cleaner = make_cleaner(force_imrad_structure=False)
    with patch("standardisation.text_cleaning.cleaner.FINAL_MARKDOWN_DIR", tmp_path):
        markdown = cleaner.clean_from_json(pub)
    assert isinstance(markdown, str)
    assert len(markdown) > 0
    assert pub.final_md_filepath is not None
    assert pub.final_md_filepath.exists()


def test_clean_from_json_does_not_call_llm_when_imrad_disabled(tmp_path):
    pub = _write_pub(tmp_path)
    cleaner = make_cleaner(force_imrad_structure=False)
    with patch("standardisation.text_cleaning.cleaner.FINAL_MARKDOWN_DIR", tmp_path), \
         patch("standardisation.text_cleaning.cleaner.LlamaClassifier") as mock_llm:
        cleaner.clean_from_json(pub)
    mock_llm.assert_not_called()


def test_clean_all_calls_clean_from_json_for_each_pub(tmp_path):
    p1 = tmp_path / "pub1"
    p2 = tmp_path / "pub2"
    p1.mkdir()
    p2.mkdir()
    pub1 = _write_pub(p1)
    pub2 = _write_pub(p2)
    cleaner = make_cleaner(force_imrad_structure=False)
    cleaner.publications = [pub1, pub2]
    with patch.object(cleaner, "clean_from_json", return_value="md") as mock_clean:
        cleaner.clean_all()
    assert mock_clean.call_count == 2


def test_clean_from_json_updates_cache(tmp_path):
    import sqlite3
    from text_download.database.database import create_database
    db = tmp_path / "cache.db"
    create_database(db)
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO cache (doi, downloaded_from, publication_filepath) VALUES (?,?,?)",
        ("10.1016/j.test.2020.01.001", "elsevier", str(tmp_path / "paper_abc123.pdf")),
    )
    conn.commit()
    conn.close()

    pub = _write_pub(tmp_path)
    cleaner = make_cleaner(force_imrad_structure=False)
    cleaner.cache = db
    with patch("standardisation.text_cleaning.cleaner.FINAL_MARKDOWN_DIR", tmp_path):
        cleaner.clean_from_json(pub)

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT final_md_filepath FROM cache WHERE doi=?",
                       ("10.1016/j.test.2020.01.001",)).fetchone()
    conn.close()
    assert row[0] is not None
    assert row[0].endswith(".md")


# ---------------------------------------------------------------------------
# _find_core_text_end
# ---------------------------------------------------------------------------

def test_find_core_text_end_inserts_end_marker_via_llm():
    cleaner = make_cleaner()
    blocks = [make_title("Introduction"), make_paragraph("body"), make_title("References")]
    mock_instance = MagicMock()
    mock_instance.classify_end.return_value = 2
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        result = cleaner._find_core_text_end(blocks)
    titles = [b.content.title_content[0].content for b in result if b.type == "title"]
    assert "end" in titles


def test_find_core_text_end_llm_returns_none_logs_warning(caplog):
    cleaner = make_cleaner()
    blocks = [make_title("Introduction"), make_paragraph("body")]
    mock_instance = MagicMock()
    mock_instance.classify_end.return_value = None
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        with caplog.at_level("WARNING"):
            result = cleaner._find_core_text_end(blocks)
    assert result == blocks
    assert "LLM could not identify end" in caplog.text


def test_find_core_text_end_no_headings_logs_warning(caplog):
    cleaner = make_cleaner()
    blocks = [make_paragraph("no headings here")]
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier") as mock_llm:
        with caplog.at_level("WARNING"):
            result = cleaner._find_core_text_end(blocks)
    mock_llm.assert_not_called()
    assert "no headings found" in caplog.text


def test_find_core_text_end_rejects_index_before_introduction(caplog):
    # LLM returns index 0 (a front-matter heading) which is before Introduction at index 2.
    # The guard should reject it and return the original block list unchanged.
    cleaner = make_cleaner()
    blocks = [
        make_title("Keywords"),
        make_paragraph("abstract text"),
        make_title("Introduction"),
        make_paragraph("body"),
        make_title("Methods"),
        make_paragraph("methods text"),
    ]
    mock_instance = MagicMock()
    mock_instance.classify_end.return_value = 0
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        with caplog.at_level("WARNING"):
            result = cleaner._find_core_text_end(blocks)
    assert result == blocks
    assert "before or at Introduction/Methods" in caplog.text
    titles = [b.content.title_content[0].content for b in result if b.type == "title"]
    assert "end" not in titles


def test_find_core_text_end_rejects_index_equal_to_introduction(caplog):
    # LLM returns the Introduction block itself — must be rejected (end must come after it).
    cleaner = make_cleaner()
    blocks = [
        make_title("Introduction"),
        make_paragraph("body"),
        make_title("Methods"),
    ]
    mock_instance = MagicMock()
    mock_instance.classify_end.return_value = 0  # index of Introduction
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        with caplog.at_level("WARNING"):
            result = cleaner._find_core_text_end(blocks)
    assert result == blocks
    assert "before or at Introduction/Methods" in caplog.text


def test_find_core_text_end_accepts_index_after_methods_when_no_introduction(caplog):
    # No Introduction heading present — Methods acts as the minimum anchor.
    # An end index after Methods should be accepted normally.
    cleaner = make_cleaner()
    blocks = [
        make_title("Methods"),
        make_paragraph("methods text"),
        make_title("Results"),
        make_paragraph("results text"),
        make_title("Acknowledgments"),
    ]
    mock_instance = MagicMock()
    mock_instance.classify_end.return_value = 4  # Acknowledgments — after Methods
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        result = cleaner._find_core_text_end(blocks)
    titles = [b.content.title_content[0].content for b in result if b.type == "title"]
    assert "end" in titles


def test_find_core_text_end_full_pipeline_empty_output_prevented():
    # Regression: simulates the Royal Society paper pattern where front-matter headings
    # (Keywords at index 0) appear before Introduction (index 2). If the LLM picks index 0,
    # _trim_to_core_text would produce an empty list. The guard must prevent this.
    cleaner = make_cleaner()
    blocks = [
        make_title("Keywords"),       # 0 — front-matter
        make_paragraph("kw text"),    # 1
        make_title("Introduction"),   # 2
        make_paragraph("intro body"), # 3
        make_title("Methods"),        # 4
        make_paragraph("methods"),    # 5
        make_title("Results"),        # 6
        make_paragraph("results"),    # 7
    ]
    mock_instance = MagicMock()
    mock_instance.classify_end.return_value = 0  # bad LLM pick — front-matter
    with patch("standardisation.text_cleaning.cleaner.LlamaClassifier", return_value=mock_instance):
        result = cleaner._find_core_text_end(blocks)
    # No "end" marker inserted — _trim_to_core_text will keep everything from Introduction onward
    trimmed = cleaner._trim_to_core_text(result)
    assert len(trimmed) > 0
    assert trimmed[0].content.title_content[0].content == "Introduction"