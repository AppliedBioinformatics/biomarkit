import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
from standardisation.text_cleaning.cleaner import Cleaner, CleaningStats


def _make_stats(status="success", **kwargs) -> CleaningStats:
    defaults = dict(
        doi="10.1/test", title="Test", publisher="Publisher", year=2020,
        document_type="XML", original_size_kb=10.0, cleaned_size_kb=8.0,
        tables_removed=0, figures_removed=0, latex_removed=0,
        h1_count=1, h2_count=2, status=status,
    )
    defaults.update(kwargs)
    return CleaningStats(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def cleaner():
    return Cleaner(publication_list=[])


@pytest.fixture
def mock_pub(tmp_path):
    content = "# Title\n\n## Introduction\n\nBody text.\n\n### References\n\nRef 1.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = tmp_path / "paper.pdf"
    pub.raw_md_filepath = md_file
    return pub, md_file, content


# ---------------------------------------------------------------------------
# extract_headings_from_content
# ---------------------------------------------------------------------------

def test_extract_headings_returns_all_heading_lines(cleaner):
    content = "# Title\n\nSome text.\n\n## Methods\n\nMore text.\n\n### References\n"
    result = cleaner.extract_headings_from_content(content)
    assert result == {1: "# Title", 5: "## Methods", 9: "### References"}


def test_extract_headings_ignores_non_heading_lines(cleaner):
    content = "Some prose.\n\nNo headings here.\n"
    assert cleaner.extract_headings_from_content(content) == {}


def test_extract_headings_empty_content(cleaner):
    assert cleaner.extract_headings_from_content("") == {}


# ---------------------------------------------------------------------------
# _apply_heading_levels
# ---------------------------------------------------------------------------

def test_apply_heading_levels_replaces_prefix(cleaner):
    content = "# Old Title\n\nText.\n\n## Old Sub\n"
    levels = {"1": "####", "5": "##"}
    result = cleaner._apply_heading_levels(content, levels)
    lines = result.splitlines()
    assert lines[0] == "#### Old Title"
    assert lines[4] == "## Old Sub"


def test_apply_heading_levels_preserves_heading_text(cleaner):
    content = "## Experimental procedure\n"
    levels = {"1": "#"}
    result = cleaner._apply_heading_levels(content, levels)
    assert result.splitlines()[0] == "# Experimental procedure"


def test_apply_heading_levels_all_four_imrad(cleaner):
    content = "## Intro\n## Materials\n## Findings\n## Interpretation\n"
    levels = {"1": "#", "2": "#", "3": "#", "4": "#"}
    result = cleaner._apply_heading_levels(content, levels)
    lines = result.splitlines()
    assert lines[0] == "# Intro"
    assert lines[1] == "# Materials"
    assert lines[2] == "# Findings"
    assert lines[3] == "# Interpretation"


def test_apply_heading_levels_preserves_heading_text_non_imrad(cleaner):
    content = "### Some Subsection\n"
    levels = {"1": "##"}
    result = cleaner._apply_heading_levels(content, levels)
    assert result.splitlines()[0] == "## Some Subsection"


def test_apply_heading_levels_ignores_out_of_range_keys(cleaner):
    content = "# Title\n"
    levels = {"99": "#"}  # line 99 doesn't exist
    result = cleaner._apply_heading_levels(content, levels)
    assert result == "# Title"


def test_apply_heading_levels_all_four_levels(cleaner):
    content = "# A\n## B\n### C\n#### D\n"
    levels = {"1": "#", "2": "##", "3": "###", "4": "####"}
    result = cleaner._apply_heading_levels(content, levels)
    lines = result.splitlines()
    assert lines[0] == "# A"
    assert lines[1] == "## B"
    assert lines[2] == "### C"
    assert lines[3] == "#### D"


# ---------------------------------------------------------------------------
# _remove_sections (non_imrad_pattern â€” exactly ### only)
# ---------------------------------------------------------------------------

def test_remove_sections_strips_triple_hash(cleaner):
    content = "# Introduction\n\nBody.\n\n### References\n\nRef 1.\n"
    result, removed = cleaner._remove_sections(content, cleaner.non_imrad_pattern)
    assert "### References" not in result
    assert "# Introduction" in result
    assert "Body." in result
    assert "References" in removed


def test_remove_sections_preserves_quadruple_hash(cleaner):
    """#### headings (metadata) must NOT be removed â€” only ### is boilerplate."""
    content = "#### Title\n\nTitle text.\n\n### Acknowledgments\n\nThanks.\n"
    result, removed = cleaner._remove_sections(content, cleaner.non_imrad_pattern)
    assert "#### Title" in result
    assert "Title text." in result
    assert "### Acknowledgments" not in result
    assert "Acknowledgments" in removed


def test_remove_sections_preserves_double_hash(cleaner):
    content = "# Introduction\n\nText.\n\n## Statistical Analysis\n\nDetails.\n"
    result, removed = cleaner._remove_sections(content, cleaner.non_imrad_pattern)
    assert "## Statistical Analysis" in result
    assert "Details." in result
    assert removed == []


def test_remove_sections_removes_subsections_of_triple_hash(cleaner):
    """Content nested under a ### heading should also be removed."""
    content = "# Results\n\nFindings.\n\n### Funding\n\nGrant info.\n\n#### Sub\n\nMore.\n\n# Discussion\n\nConclusion.\n"
    result, removed = cleaner._remove_sections(content, cleaner.non_imrad_pattern)
    assert "### Funding" not in result
    assert "Grant info." not in result
    assert "# Results" in result
    assert "# Discussion" in result
    assert "Funding" in removed


def test_remove_sections_no_triple_hash_unchanged(cleaner):
    content = "# Intro\n\nText.\n\n## Methods\n\nDetails.\n"
    result, removed = cleaner._remove_sections(content, cleaner.non_imrad_pattern)
    assert result == content
    assert removed == []


# ---------------------------------------------------------------------------
# _get_output_path
# ---------------------------------------------------------------------------

def test_get_output_path_same_dir_by_default(cleaner):
    from config import FINAL_MARKDOWN_DIR
    pub = Mock()
    pub.publication_filepath = Path("/data/papers/mypaper.pdf")
    pub.raw_md_filepath = Path("/data/papers/mypaper.md")
    result = cleaner._get_output_path(pub)
    assert result == FINAL_MARKDOWN_DIR / "mypaper.cleaned.md"


def test_get_output_path_uses_output_dir_when_set(tmp_path):
    cleaner = Cleaner(publication_list=[], output_dir=tmp_path)
    pub = Mock()
    pub.publication_filepath = Path("/data/papers/mypaper.pdf")
    pub.raw_md_filepath = Path("/data/papers/mypaper.md")
    result = cleaner._get_output_path(pub)
    assert result == tmp_path / "mypaper.cleaned.md"


def test_get_output_path_uses_raw_md_filepath_stem(tmp_path):
    from unittest.mock import MagicMock
    from standardisation.text_cleaning.cleaner import Cleaner

    pub = MagicMock()
    pub.publication_filepath = tmp_path / "paper_abc.pdf"
    pub.raw_md_filepath = tmp_path / "paper_abc_raw.md"

    cleaner = Cleaner(publication_list=[], output_dir=tmp_path)
    result = cleaner._get_output_path(pub)

    assert result.name == "paper_abc_raw.cleaned.md"
    assert result.parent == tmp_path


# ---------------------------------------------------------------------------
# remove_boilerplate
# ---------------------------------------------------------------------------

def test_remove_boilerplate_without_classifier_classifies_by_regex(tmp_path):
    content = "# Title\n\n## Introduction\n\nBody text.\n\n## References\n\nRefs.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.status == "success"
    output = (tmp_path / "paper.cleaned.md").read_text(encoding="utf-8")
    assert "## Introduction" in output
    assert "Body text." in output
    assert "References" not in output  # regex classifies as DELETE


def test_remove_boilerplate_with_classifier_resolves_unresolved(tmp_path):
    content = "## Introduction\n\nBody.\n\n## Wheat Genomics\n\nDetails.\n\n## References\n\nRef 1.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    classifier = Mock()
    # LLM classifies unresolved "## Wheat Genomics" (line 5) as body text
    classifier.classify.return_value = {"5": "body"}

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path, classifier=classifier)
    result = cleaner.remove_boilerplate(pub)

    assert result.status == "success"
    output = (tmp_path / "paper.cleaned.md").read_text(encoding="utf-8")
    assert "## Introduction" in output
    assert "Body." in output
    assert "References" not in output
    assert "Ref 1." not in output


def test_remove_boilerplate_classifier_failure_treats_unresolved_as_body(tmp_path):
    content = "## Introduction\n\nText.\n\n## Wheat Genomics\n\nDetails.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    classifier = Mock()
    classifier.classify.return_value = None  # simulate LLM failure

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path, classifier=classifier)
    result = cleaner.remove_boilerplate(pub)

    assert result.status == "success"
    output = (tmp_path / "paper.cleaned.md").read_text(encoding="utf-8")
    # Unresolved heading treated as body text (demoted, not deleted)
    assert "Wheat Genomics" in output
    assert "Details." in output


def test_remove_boilerplate_returns_none_for_missing_file(cleaner):
    pub = Mock()
    pub.publication_filepath = Path("/nonexistent/paper.pdf")
    pub.raw_md_filepath = Path("/nonexistent/paper.md")
    result = cleaner.remove_boilerplate(pub)
    assert result.status == "failure"


# ---------------------------------------------------------------------------
# clean_all
# ---------------------------------------------------------------------------

def test_clean_all_returns_successes_and_failures_tuple(cleaner):
    pub1, pub2 = Mock(), Mock()
    pub1.final_md_filepath = None
    pub2.final_md_filepath = None
    cleaner.publications = [pub1, pub2]

    success_stat = _make_stats(status="success")
    failure_stat = _make_stats(status="failure")

    with patch.object(cleaner, "remove_boilerplate", side_effect=[success_stat, failure_stat]):
        successes, failures = cleaner.clean_all()

    assert len(successes) == 1
    assert successes[0].status == "success"
    assert len(failures) == 1
    assert failures[0].status == "failure"


def test_clean_all_all_succeed(cleaner):
    pubs = [Mock(), Mock(), Mock()]
    for p in pubs:
        p.final_md_filepath = None
    cleaner.publications = pubs

    with patch.object(cleaner, "remove_boilerplate", return_value=_make_stats(status="success")):
        successes, failures = cleaner.clean_all()

    assert len(successes) == 3
    assert failures == []


def test_clean_all_all_fail(cleaner):
    pubs = [Mock(), Mock()]
    cleaner.publications = pubs

    with patch.object(cleaner, "remove_boilerplate", return_value=_make_stats(status="failure")):
        successes, failures = cleaner.clean_all()

    assert successes == []
    assert len(failures) == 2


# ---------------------------------------------------------------------------
# _replace_tables
# ---------------------------------------------------------------------------

def test_replace_tables_replaces_simple_pipe_table(cleaner):
    content = "Some text.\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nMore text."
    result = cleaner._replace_tables(content)
    assert "<table_removed>" in result
    assert "| A | B |" not in result
    assert "| 1 | 2 |" not in result
    assert "Some text." in result
    assert "More text." in result


def test_replace_tables_replaces_bold_caption_and_pipe_table(cleaner):
    content = "Text.\n\n**Table 1**: Results summary.\n| A | B |\n| --- | --- |\n| x | y |\n\nEnd."
    result = cleaner._replace_tables(content)
    assert result.count("<table_removed>") == 1
    assert "**Table 1**" not in result
    assert "| A | B |" not in result


def test_replace_tables_plain_text_caption_formats(cleaner):
    """Plain-text caption variants used in unpaywall papers."""
    cases = [
        "Table 1 Summary of trials\n\n| A |\n| --- |\n| 1 |\n",
        "Table 1. Virulence profile.\n\n| A |\n| --- |\n| 1 |\n",
        "TABLE 1 | Ten pairs of isolates.\n\n| A |\n| --- |\n| 1 |\n",
    ]
    for content in cases:
        result = cleaner._replace_tables(content)
        assert result.count("<table_removed>") == 1, f"Expected 1 <table> for: {content!r}"
        assert "| A |" not in result


def test_replace_tables_html_table(cleaner):
    content = "Text.\n\n<table><tr><td>A</td><td>B</td></tr></table>\n\nMore."
    result = cleaner._replace_tables(content)
    assert "<table><tr>" not in result
    assert result.count("<table_removed>") == 1
    assert "Text." in result
    assert "More." in result


def test_replace_tables_html_table_with_plain_caption(cleaner):
    content = "Table 1 Names of landraces.\n\n<table><tr><td>A</td></tr></table>\n\nEnd."
    result = cleaner._replace_tables(content)
    assert result.count("<table_removed>") == 1
    assert "Names of landraces" not in result


def test_replace_tables_multiple_tables_mixed(cleaner):
    content = (
        "Intro.\n\n"
        "| A |\n| --- |\n| 1 |\n\n"
        "Middle.\n\n"
        "Table 2. HTML table.\n\n<table><tr><td>B</td></tr></table>\n\n"
        "End."
    )
    result = cleaner._replace_tables(content)
    assert result.count("<table_removed>") == 2
    assert "| A |" not in result
    assert "<tr>" not in result
    assert "Intro." in result
    assert "Middle." in result


def test_replace_tables_preserves_content_without_tables(cleaner):
    content = "# Introduction\n\nNo tables here.\n\n## Methods\n\nJust text.\n"
    assert cleaner._replace_tables(content) == content


def test_replace_tables_non_caption_line_before_table_preserved(cleaner):
    """A regular prose line before a table should not be consumed."""
    content = "This sentence ends.\n| A |\n| --- |\n| 1 |\n"
    result = cleaner._replace_tables(content)
    assert "This sentence ends." in result
    assert "<table_removed>" in result


def test_replace_tables_caption_separated_by_blank_line(cleaner):
    """Elsevier format: bold caption + blank line + pipe table â€” caption must be consumed."""
    content = "**Table 2**: Disease severity data.\n\n| A | B |\n| --- | --- |\n| x | y |\n\nEnd."
    result = cleaner._replace_tables(content)
    assert result.count("<table_removed>") == 1
    assert "**Table 2**" not in result
    assert "| A | B |" not in result
    assert "End." in result


def test_replace_tables_multiple_elsevier_style(cleaner):
    """Multiple Elsevier-style tables each with blank line between caption and table."""
    content = (
        "**Table 1**: First table.\n\n| A |\n| --- |\n| 1 |\n\n"
        "**Table 2**: Second table.\n\n| B |\n| --- |\n| 2 |\n\nEnd."
    )
    result = cleaner._replace_tables(content)
    assert result.count("<table_removed>") == 2
    assert "**Table 1**" not in result
    assert "**Table 2**" not in result
    assert "End." in result


def test_replace_tables_footnotes_after_pipe_table_removed(cleaner):
    """^a^ footnote lines immediately after a pipe table are consumed."""
    content = (
        "**Table 1**: Results.\n\n"
        "| Trait | Avg. ^a^ | SD ^b^ |\n| --- | --- | --- |\n| YR | 1.2 | 0.3 |\n\n"
        "^a^ Average.\n^b^ Standard deviation.\n\n"
        "More text."
    )
    result = cleaner._replace_tables(content)
    assert result.count("<table_removed>") == 1
    assert "^a^ Average" not in result
    assert "^b^ Standard" not in result
    assert "More text." in result


def test_replace_tables_footnotes_multiple_tables(cleaner):
    """Footnotes after each of multiple tables are all removed."""
    content = (
        "**Table 1**: First.\n\n| A |\n| --- |\n| 1 |\n\n"
        "^a^ Note one.\n\n"
        "**Table 2**: Second.\n\n| B |\n| --- |\n| 2 |\n\n"
        "^a^ Note two.\n^b^ Note three.\n\n"
        "End."
    )
    result = cleaner._replace_tables(content)
    assert result.count("<table_removed>") == 2
    assert "Note one" not in result
    assert "Note two" not in result
    assert "Note three" not in result
    assert "End." in result


def test_replace_tables_non_footnote_line_after_table_preserved(cleaner):
    """A line after a table that doesn't start with ^x^ should not be consumed."""
    content = "| A |\n| --- |\n| 1 |\n\nThis is prose, not a footnote.\n"
    result = cleaner._replace_tables(content)
    assert "This is prose, not a footnote." in result


# ---------------------------------------------------------------------------
# remove_boilerplate always replaces tables
# ---------------------------------------------------------------------------

def test_remove_boilerplate_always_replaces_tables(tmp_path):
    content = "## Introduction\n\nText.\n\n| Col |\n| --- |\n| val |\n\nMore.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    cleaner.remove_boilerplate(pub)

    output = (tmp_path / "paper.cleaned.md").read_text(encoding="utf-8")
    assert "<table_removed>" in output
    assert "| Col |" not in output


# ---------------------------------------------------------------------------
# _replace_latex
# ---------------------------------------------------------------------------

def test_replace_latex_inline(cleaner):
    content = "Resistance was $87 \\%$ in all trials."
    result = cleaner._replace_latex(content)
    assert "<latex_removed>" in result
    assert "$87" not in result
    assert "Resistance was" in result
    assert "in all trials." in result


def test_replace_latex_display_block(cleaner):
    content = "The model is:\n\n$$\ny = \\mu + a + e\n$$\n\nwhere y is the response."
    result = cleaner._replace_latex(content)
    assert "<latex_removed>" in result
    assert "$$" not in result
    assert "y = \\mu" not in result
    assert "where y is the response." in result


def test_replace_latex_multiple_inline(cleaner):
    content = "Values $p < 0.05$ and $R^2 = 0.91$ were significant."
    result = cleaner._replace_latex(content)
    assert result.count("<latex_removed>") == 2
    assert "$" not in result


def test_replace_latex_display_before_inline(cleaner):
    """Display $$ blocks must be replaced before inline to avoid misparse."""
    content = "$$\na + b\n$$\n\nAlso $x = 1$ inline."
    result = cleaner._replace_latex(content)
    assert result.count("<latex_removed>") == 2
    assert "$$" not in result
    assert "$x" not in result


def test_replace_latex_no_math_unchanged(cleaner):
    content = "No equations here. Just plain text with a price of $50."
    # Single $ with no closing $ on same line â€” should not match inline pattern
    result = cleaner._replace_latex(content)
    assert "$50" in result


def test_replace_latex_preserves_surrounding_text(cleaner):
    content = "# Results\n\nThe value $F_{2:3}$ was high.\n\n## Discussion\n"
    result = cleaner._replace_latex(content)
    assert "# Results" in result
    assert "## Discussion" in result
    assert "The value" in result
    assert "was high." in result


# ---------------------------------------------------------------------------
# remove_boilerplate always replaces latex
# ---------------------------------------------------------------------------

def test_remove_boilerplate_always_replaces_latex(tmp_path):
    content = "## Introduction\n\nThe equation $E = mc^2$ is well known.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    cleaner.remove_boilerplate(pub)

    output = (tmp_path / "paper.cleaned.md").read_text(encoding="utf-8")
    assert "<latex_removed>" in output
    assert "$E = mc^2$" not in output


# ---------------------------------------------------------------------------
# _replace_figures
# ---------------------------------------------------------------------------

def test_replace_figures_pdf_image_then_caption(cleaner):
    """Image line immediately followed by a Fig caption â†’ <figure>."""
    content = "Text.\n\n![](images/abc.jpg)  \nFig. 1 A scatter plot of results.\n\nMore text."
    result = cleaner._replace_figures(content)
    assert "<figure_removed>" in result
    assert "![](images/abc.jpg)" not in result
    assert "Fig. 1" not in result
    assert "Text." in result
    assert "More text." in result


def test_replace_figures_pdf_image_blank_line_then_caption(cleaner):
    """Image line separated from caption by a blank line â†’ both consumed."""
    content = "Text.\n\n![](images/abc.jpg)\n\nFig. 2 Another figure.\n\nEnd."
    result = cleaner._replace_figures(content)
    assert result.count("<figure_removed>") == 1
    assert "![](images/abc.jpg)" not in result
    assert "Fig. 2" not in result


def test_replace_figures_figure_all_caps_pipe(cleaner):
    """FIGURE N | caption format."""
    content = "![](images/x.jpg)\nFIGURE 1 | Heat map of isolates.\n"
    result = cleaner._replace_figures(content)
    assert "<figure_removed>" in result
    assert "FIGURE 1" not in result


def test_replace_figures_figure_full_word(cleaner):
    """Figure N. caption format."""
    content = "![](images/x.jpg)\nFigure 2. LOD profile obtained with interval mapping.\n"
    result = cleaner._replace_figures(content)
    assert "<figure_removed>" in result
    assert "Figure 2" not in result


def test_replace_figures_elsevier_bracketed(cleaner):
    """[Fig. N: caption] bracketed format used by Elsevier XML papers."""
    content = "# Figures\n\n[Fig. 1: Frequency of genotypes.]\n\n[Fig. 2: Neighbor joining tree.]\n"
    result = cleaner._replace_figures(content)
    assert result.count("<figure_removed>") == 2
    assert "[Fig. 1:" not in result
    assert "[Fig. 2:" not in result
    assert "# Figures" in result


def test_replace_figures_image_without_caption_kept(cleaner):
    """Image line with no following Fig caption should be left unchanged."""
    content = "![](images/logo.png)\n\nSome unrelated text.\n"
    result = cleaner._replace_figures(content)
    assert "![](images/logo.png)" in result
    assert "<figure_removed>" not in result


def test_replace_figures_multiple_figures(cleaner):
    content = (
        "Intro.\n\n"
        "![](images/a.jpg)\nFig. 1 First figure.\n\n"
        "Middle.\n\n"
        "[Fig. 2: Second figure.]\n\n"
        "End."
    )
    result = cleaner._replace_figures(content)
    assert result.count("<figure_removed>") == 2
    assert "Fig. 1" not in result
    assert "Fig. 2" not in result
    assert "Intro." in result
    assert "Middle." in result


def test_replace_figures_no_figures_unchanged(cleaner):
    content = "# Introduction\n\nNo figures here.\n\n## Methods\n\nJust text.\n"
    assert cleaner._replace_figures(content) == content


# ---------------------------------------------------------------------------
# remove_boilerplate always replaces figures
# ---------------------------------------------------------------------------

def test_remove_boilerplate_always_replaces_figures(tmp_path):
    """Figures are always replaced in the new pipeline."""
    content = "## Introduction\n\nText.\n\n![](images/a.jpg)\nFig. 1 A result figure.\n\nMore.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    cleaner.remove_boilerplate(pub)

    output = (tmp_path / "paper.cleaned.md").read_text(encoding="utf-8")
    assert "<figure_removed>" in output
    assert "Fig. 1" not in output


# ---------------------------------------------------------------------------
# CleaningStats â€” stat counting tests
# ---------------------------------------------------------------------------

def test_remove_boilerplate_counts_tables_removed(tmp_path):
    content = (
        "## Introduction\n\n"
        "**Table 1**: First.\n\n| A |\n| --- |\n| 1 |\n\n"
        "**Table 2**: Second.\n\n| B |\n| --- |\n| 2 |\n\n"
        "End.\n"
    )
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.tables_removed == 2


def test_remove_boilerplate_counts_figures_removed(tmp_path):
    content = "## Introduction\n\nText.\n\n![](images/a.jpg)\nFig. 1 A result figure.\n\nMore.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.figures_removed == 1


def test_remove_boilerplate_counts_latex_removed(tmp_path):
    content = (
        "## Introduction\n\n"
        "The model is:\n\n$$\ny = a + e\n$$\n\n"
        "And $p < 0.05$ inline.\n"
    )
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.latex_removed == 2


def test_remove_boilerplate_counts_headers(tmp_path):
    content = "## Introduction\n\nText.\n\n## Methods\n\nMore.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.h2_count == 2


def test_remove_boilerplate_records_file_sizes(tmp_path):
    content = "## Introduction\n\n" + "Word " * 500 + "\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.original_size_kb > 0
    assert result.cleaned_size_kb <= result.original_size_kb


# ---------------------------------------------------------------------------
# cache update
# ---------------------------------------------------------------------------

def test_remove_boilerplate_updates_cache_on_success(tmp_path):
    from text_extraction.database.database import create_database, insert_row, get_row_for_doi
    content = "## Introduction\n\nText.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file
    pub.doi = "10.1/cache-test"

    db_path = tmp_path / "test_cache.sqlite"
    create_database(db_path)
    insert_row(doi="10.1/cache-test", downloaded_from="test", publication_filepath=str(md_file), db_path=db_path)

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path, cache=db_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.status == "success"
    row = get_row_for_doi("10.1/cache-test", db_path)
    assert row["final_md_filepath"] is not None
    assert row["final_md_filepath"].endswith(".cleaned.md")


def test_remove_boilerplate_does_not_update_cache_when_no_cache_set(tmp_path):
    content = "## Introduction\n\nText.\n"
    md_file = tmp_path / "paper.md"
    md_file.write_text(content, encoding="utf-8")
    pub = Mock()
    pub.publication_filepath = md_file
    pub.raw_md_filepath = md_file
    pub.doi = "10.1/no-cache"

    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(pub)

    assert result.status == "success"
    assert cleaner.cache is None