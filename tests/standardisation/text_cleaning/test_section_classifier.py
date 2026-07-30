import pytest
from standardisation.text_cleaning.section_classifier import (
    classify_heading, classify_headings, _is_title_heading, Action,
)


@pytest.mark.parametrize("normalised, expected", [
    # Major sections
    ("introduction", Action.INTRODUCTION),
    ("background", Action.INTRODUCTION),
    ("methods", Action.METHODS),
    ("materials and methods", Action.METHODS),
    ("experimental", Action.METHODS),
    ("methodology", Action.METHODS),
    ("results", Action.RESULTS),
    ("results and discussion", Action.RESULTS),
    ("characteristics", Action.RESULTS),
    ("findings", Action.RESULTS),
    ("discussion", Action.DISCUSSION),
    ("conclusion", Action.DISCUSSION),
    ("conclusions", Action.DISCUSSION),
    ("concluding remarks", Action.DISCUSSION),
    # Delete â€” front/back matter
    ("abstract", Action.DELETE),
    ("keywords", Action.DELETE),
    ("references", Action.DELETE),
    ("literature cited", Action.DELETE),
    ("bibliography", Action.DELETE),
    ("acknowledgments", Action.DELETE),
    ("acknowledgements", Action.DELETE),
    ("funding", Action.DELETE),
    ("author contributions", Action.DELETE),
    ("conflict of interest", Action.DELETE),
    ("supplementary material", Action.DELETE),
    ("supplementary information", Action.DELETE),
    ("supporting information", Action.DELETE),
    ("additional information", Action.DELETE),
    ("additional files", Action.DELETE),
    ("abbreviations", Action.DELETE),
    ("declarations", Action.DELETE),
    ("data availability", Action.DELETE),
    ("code availability", Action.DELETE),
    ("ethics statement", Action.DELETE),
    ("ethics approval and consent to participate", Action.DELETE),
    ("compliance with ethical standards", Action.DELETE),
    ("consent for publication", Action.DELETE),
    ("orcid", Action.DELETE),
    ("competing interests", Action.DELETE),
    ("correspondence", Action.DELETE),
    ("core ideas", Action.DELETE),
    ("citation:", Action.DELETE),
    ("citation", Action.DELETE),
    ("figures", Action.DELETE),
    ("tables", Action.DELETE),
    ("author details", Action.DELETE),
    ("author information", Action.DELETE),
])
def test_classify_heading_known(normalised, expected):
    assert classify_heading(normalised) == expected


def test_classify_heading_unknown_returns_none():
    assert classify_heading("plant materials") is None
    assert classify_heading("qtl analysis") is None
    assert classify_heading("some random subsection") is None


def test_is_title_heading():
    assert _is_title_heading("# Title of a Paper") is True
    assert _is_title_heading("## Introduction") is False
    assert _is_title_heading("### Subsection") is False


def test_h1_title_classified_as_delete():
    headings = {
        1: "# Some Paper Title About Wheat Rust",
        5: "## Abstract",
        10: "## Introduction",
    }
    result = classify_headings(headings)
    assert result[1] == Action.DELETE
    assert result[5] == Action.DELETE
    assert result[10] == Action.INTRODUCTION


def test_classify_headings_all_resolved():
    headings = {
        5: "## Introduction",
        20: "## Materials and Methods",
        50: "## Results",
        80: "## Discussion",
        95: "## References",
    }
    result = classify_headings(headings)
    assert result[5] == Action.INTRODUCTION
    assert result[20] == Action.METHODS
    assert result[50] == Action.RESULTS
    assert result[80] == Action.DISCUSSION
    assert result[95] == Action.DELETE
    assert result.unresolved == {}


def test_classify_headings_with_unresolved():
    headings = {
        5: "## Introduction",
        15: "### Plant Materials",
        20: "## Methods",
        30: "### Some Weird Section",
    }
    result = classify_headings(headings)
    assert result[5] == Action.INTRODUCTION
    assert result[20] == Action.METHODS
    assert 15 in result.unresolved
    assert 30 in result.unresolved


def test_classify_headings_results_and_discussion_no_separate_discussion():
    headings = {
        5: "## Introduction",
        20: "## Methods",
        50: "## Results and Discussion",
        80: "## References",
    }
    result = classify_headings(headings)
    assert result[50] == Action.RESULTS
    assert Action.DISCUSSION not in result.values()