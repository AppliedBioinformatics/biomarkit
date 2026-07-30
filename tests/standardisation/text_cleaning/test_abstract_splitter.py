"""Tests for abstract+introduction splitting logic."""
import pytest
from standardisation.text_cleaning.abstract_splitter import find_intro_after_abstract
from standardisation.text_cleaning.section_classifier import Action, ClassificationResult


def _make_classification(actions_dict):
    result = ClassificationResult()
    result.actions = dict(actions_dict)
    return result


def test_splits_when_intro_missing_and_abstract_present():
    lines = [
        "## Abstract",                  # line 1
        "This is the abstract text.",   # line 2
        "More abstract content here.",  # line 3
        "",                             # line 4
        "This is actually the intro.",  # line 5
        "More intro content.",          # line 6
        "## Methods",                   # line 7
    ]
    classification = _make_classification({
        1: Action.DELETE,   # Abstract
        7: Action.METHODS,
    })
    known_abstract = "This is the abstract text. More abstract content here."

    result = find_intro_after_abstract(lines, classification, known_abstract)
    assert result is not None
    assert result == 4  # intro starts at line 4 (first line after abstract text ends)


def test_no_split_when_intro_already_exists():
    lines = [
        "## Abstract",
        "Abstract text.",
        "## Introduction",
        "Intro text.",
        "## Methods",
    ]
    classification = _make_classification({
        1: Action.DELETE,
        3: Action.INTRODUCTION,
        5: Action.METHODS,
    })
    result = find_intro_after_abstract(lines, classification, "Abstract text.")
    assert result is None


def test_no_split_when_no_abstract_heading():
    lines = [
        "## Introduction",
        "Intro text.",
        "## Methods",
        "Methods text.",
    ]
    classification = _make_classification({
        1: Action.INTRODUCTION,
        3: Action.METHODS,
    })
    result = find_intro_after_abstract(lines, classification, "Some abstract")
    assert result is None


def test_no_split_when_abstract_text_fills_entire_section():
    """If the known abstract matches all content up to next heading, no intro to split."""
    lines = [
        "## Abstract",
        "This is the full abstract text and nothing else.",
        "## Methods",
        "Methods text.",
    ]
    classification = _make_classification({
        1: Action.DELETE,
        3: Action.METHODS,
    })
    known = "This is the full abstract text and nothing else."
    result = find_intro_after_abstract(lines, classification, known)
    assert result is None


def test_split_with_fuzzy_match():
    """Abstract in markdown may differ slightly from Scopus abstract."""
    lines = [
        "## ABSTRACT",
        "Stripe rust caused by Puccinia striiformis is important.",
        "We studied resistance in wheat cultivars.",
        "",
        "The genetic basis of stripe rust resistance",
        "has been extensively studied worldwide.",
        "## MATERIALS AND METHODS",
    ]
    classification = _make_classification({
        1: Action.DELETE,
        7: Action.METHODS,
    })
    # Scopus abstract has slightly different formatting
    known = "Stripe rust, caused by Puccinia striiformis, is important. We studied resistance in wheat cultivars."

    result = find_intro_after_abstract(lines, classification, known)
    assert result is not None
    assert result == 4  # intro starts at line 4 (first line after abstract text ends)
