import pytest
from pathlib import Path
from unittest.mock import Mock
from standardisation.text_cleaning.cleaner import Cleaner


def test_integration_with_real_markdown_file(tmp_path):
    """Integration test: regex classifier handles standard headings, boilerplate is stripped."""

    sample_content = """# Identification of wheat rust resistance genes

## Abstract

This study identifies genetic resistance to wheat rust diseases.

## Introduction

Wheat rust is a major agricultural problem worldwide.

## Methods

We used molecular markers to identify resistance genes.

## Results

Five QTL regions were identified on chromosomes 1A, 2B, and 6D.

## Discussion

These findings provide new insights into rust resistance.

## Acknowledgments

We thank Dr. Smith for technical assistance and the research team.

## Funding

This research was supported by USDA grant 12345 and NSF grant 67890.

## Author contributions

J.D. designed experiments. A.B. analyzed data. C.E. wrote the manuscript.

## Competing interests

The authors declare no competing financial interests.

## References

1. Smith, J. et al. Wheat genetics. Nature. 2023.
2. Jones, A. Rust resistance mechanisms. Science. 2022.
"""

    input_file = tmp_path / "test_paper.md"
    input_file.write_text(sample_content, encoding="utf-8")

    publication = Mock()
    publication.publication_filepath = input_file
    publication.raw_md_filepath = input_file

    # No classifier needed â€” regex handles all standard headings
    cleaner = Cleaner(publication_list=[publication], output_dir=tmp_path)
    result = cleaner.remove_boilerplate(publication)

    assert result.status == "success"
    cleaned = (tmp_path / "test_paper.cleaned.md").read_text(encoding="utf-8")

    # Boilerplate sections removed
    assert "Acknowledgments" not in cleaned
    assert "Funding" not in cleaned
    assert "Author contributions" not in cleaned
    assert "Competing interests" not in cleaned
    assert "References" not in cleaned

    # Scientific content preserved
    assert "Introduction" in cleaned
    assert "Methods" in cleaned
    assert "Results" in cleaned
    assert "Discussion" in cleaned
    assert "QTL regions were identified" in cleaned
    assert "Wheat rust is a major agricultural problem" in cleaned