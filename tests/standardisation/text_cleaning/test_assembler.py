import pytest
from standardisation.text_cleaning.assembler import assemble
from standardisation.text_cleaning.section_classifier import Action


def test_basic_four_section_assembly():
    content = "\n".join([
        "Some metadata at top",
        "Author info etc",
        "## Introduction",
        "Intro paragraph one.",
        "Intro paragraph two.",
        "## Materials and Methods",
        "Methods paragraph.",
        "## Results",
        "Results paragraph.",
        "## Discussion",
        "Discussion paragraph.",
        "## References",
        "Ref 1",
        "Ref 2",
    ])
    actions = {
        3: Action.INTRODUCTION,
        6: Action.METHODS,
        8: Action.RESULTS,
        10: Action.DISCUSSION,
        12: Action.DELETE,
    }
    result = assemble(content, actions)
    assert "## Introduction" in result
    assert "Intro paragraph one." in result
    assert "## Methods" in result
    assert "Methods paragraph." in result
    assert "## Results" in result
    assert "Results paragraph." in result
    assert "## Discussion" in result
    assert "Discussion paragraph." in result
    assert "Some metadata" not in result
    assert "Author info" not in result
    assert "Ref 1" not in result


def test_no_discussion_section():
    content = "\n".join([
        "## Introduction",
        "Intro text.",
        "## Methods",
        "Methods text.",
        "## Results and Discussion",
        "Combined text.",
        "## References",
        "Ref 1",
    ])
    actions = {
        1: Action.INTRODUCTION,
        3: Action.METHODS,
        5: Action.RESULTS,
        7: Action.DELETE,
    }
    result = assemble(content, actions)
    assert "## Introduction" in result
    assert "## Methods" in result
    assert "## Results" in result
    assert "## Discussion" not in result
    assert "Ref 1" not in result


def test_subsection_headings_preserved():
    """Unclassified subheadings inside a major section are kept as ### subheadings."""
    content = "\n".join([
        "## Introduction",
        "Intro text.",
        "## Methods",
        "### Plant Materials",
        "Plant text.",
        "### DNA Extraction",
        "DNA text.",
        "## Results",
        "Results text.",
    ])
    actions = {
        1: Action.INTRODUCTION,
        3: Action.METHODS,
        8: Action.RESULTS,
    }
    result = assemble(content, actions)
    assert "## Methods" in result
    assert "### Plant Materials" in result
    assert "Plant text." in result
    assert "### DNA Extraction" in result
    assert "DNA text." in result


def test_front_matter_stripped():
    content = "\n".join([
        "Title of Paper",
        "Author 1, Author 2",
        "Some University",
        "",
        "## Abstract",
        "Abstract text here.",
        "",
        "## Introduction",
        "Real content starts.",
    ])
    actions = {
        5: Action.DELETE,
        8: Action.INTRODUCTION,
    }
    result = assemble(content, actions)
    assert "Title of Paper" not in result
    assert "Author 1" not in result
    assert "Abstract text" not in result
    assert "## Introduction" in result
    assert "Real content starts." in result


def test_empty_content():
    result = assemble("", {})
    assert result == ""


def test_body_action_preserves_heading_as_subheading():
    """A BODY-classified heading is kept as a ### subheading, normalising its level."""
    content = "\n".join([
        "## Introduction",
        "Intro text.",
        "## Methods",
        "#### Subsection One",
        "Sub text.",
        "## Results",
        "Results text.",
    ])
    actions = {
        1: Action.INTRODUCTION,
        3: Action.METHODS,
        4: Action.BODY,
        6: Action.RESULTS,
    }
    result = assemble(content, actions)
    # Deeper-level heading is normalised to ### (not left as #### or flattened).
    assert "### Subsection One" in result
    assert "#### Subsection One" not in result
    assert "Sub text." in result
