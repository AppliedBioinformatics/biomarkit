# tests/standardisation/text_cleaning/test_standardiser_integration.py
"""End-to-end test with realistic markdown samples from different publishers."""
import pytest
from pathlib import Path
from unittest.mock import Mock
from standardisation.text_cleaning.cleaner import Cleaner


SPRINGER_SAMPLE = """\
# Mapping of quantitative trait loci for grain yield

Author A, Author B

University of Agriculture, Research Institute

## Abbreviations

QTL, quantitative trait loci; MAS, marker-assisted selection

## Abstract

We mapped QTL for grain yield in wheat.

**Keywords:** wheat, QTL, grain yield

## Introduction

Wheat is the most important cereal crop.

## Materials and methods

### Plant materials and breeding plan

Two wheat cultivars were crossed.

### DNA extractions and PCR protocol

DNA was extracted using CTAB method.

### Statistical analysis

Data were analysed using R.

## Results and discussion

### QTL mapping

Three QTL were identified.

| QTL | Chromosome | LOD |
| --- | --- | --- |
| Q1 | 1B | 5.2 |

### Field evaluation

Yield was measured in three environments.

## Conclusion

The identified QTL can be used for MAS.

## Declarations

### Ethics approval

Not applicable.

### Funding

This work was funded by Grant X.

## References

1. Smith et al. (2020) Wheat genetics.
2. Jones et al. (2019) QTL mapping.
"""


FRONTIERS_SAMPLE = """\
# Genome-Wide Association Study of Stripe Rust Resistance

Author C, Author D

## ABSTRACT

A GWAS was conducted to identify loci for stripe rust resistance.

## INTRODUCTION

Stripe rust is a major disease of wheat worldwide.

## MATERIALS AND METHODS

### Plant Material, Inoculation, and Phenotypic Scoring

A panel of 200 wheat accessions was used.

### Genotyping

SNP genotyping was performed using the 90K array.

## RESULTS

### QTL Identified on Chromosome 2B

A major QTL was detected on chromosome 2B.

![](images/manhattan_plot.jpg)

Fig. 1 Manhattan plot of GWAS results.

### QTL Identified on Chromosome 5A

A minor QTL was found on 5A.

## DISCUSSION

### Comparison With Previously Published Yr Genes

The 2B QTL co-localises with Yr44.

## ACKNOWLEDGMENTS

We thank the field team.

## REFERENCES

1. Reference one.
"""


def _make_pub(md_file):
    pub = Mock()
    pub.doi = "10.1234/test"
    pub.title = "Test Paper"
    pub.publisher = "test_publisher"
    pub.year = 2024
    pub.document_type = "pdf"
    pub.raw_md_filepath = md_file
    pub.publication_filepath = md_file
    pub.final_md_filepath = None
    return pub


def test_springer_combined_results_discussion(tmp_path):
    md_file = tmp_path / "springer_paper.md"
    md_file.write_text(SPRINGER_SAMPLE, encoding="utf-8")

    pub = _make_pub(md_file)
    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path / "output")
    successes, failures = cleaner.clean_all()

    assert len(successes) == 1
    assert len(failures) == 0

    result = pub.final_md_filepath.read_text(encoding="utf-8")

    # Should have Introduction, Methods, Results
    assert "## Introduction" in result
    assert "## Methods" in result
    assert "## Results" in result

    # Combined "Results and discussion" â†’ Results, no separate Discussion
    assert "Three QTL were identified." in result

    # Metadata stripped
    assert "Abbreviations" not in result.split("## Introduction")[0]
    assert "Keywords" not in result.split("## Introduction")[0]
    assert "Author A" not in result
    assert "Smith et al." not in result

    # Tables replaced
    assert "<table_removed>" in result

    # Subsections within IMRaD sections preserved as ### subheadings
    assert "### Plant materials and breeding plan" in result
    assert "### QTL mapping" in result
    # Back-matter subheadings (under deleted sections) are gone
    assert "### Ethics approval" not in result
    assert "### Funding" not in result


def test_frontiers_all_caps_headings(tmp_path):
    md_file = tmp_path / "frontiers_paper.md"
    md_file.write_text(FRONTIERS_SAMPLE, encoding="utf-8")

    pub = _make_pub(md_file)
    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path / "output")
    successes, failures = cleaner.clean_all()

    assert len(successes) == 1

    result = pub.final_md_filepath.read_text(encoding="utf-8")

    # Should have all four sections (Frontiers has separate Discussion)
    assert "## Introduction" in result
    assert "## Methods" in result
    assert "## Results" in result
    assert "## Discussion" in result

    # Content preserved
    assert "Stripe rust is a major disease" in result
    assert "A panel of 200 wheat accessions" in result

    # Figures replaced
    assert "<figure_removed>" in result

    # Back matter stripped
    assert "We thank the field team" not in result
    assert "Reference one" not in result

    # Subsections within IMRaD sections preserved as ### subheadings
    assert "### Genotyping" in result
    assert "### QTL Identified on Chromosome 2B" in result


def test_no_major_sections_returns_empty(tmp_path):
    """A document with no recognisable IMRaD sections produces empty output."""
    content = "# Title\n\nSome text.\n\n## Acknowledgments\n\nThanks.\n"
    md_file = tmp_path / "no_sections.md"
    md_file.write_text(content, encoding="utf-8")

    pub = _make_pub(md_file)
    cleaner = Cleaner(publication_list=[pub], output_dir=tmp_path / "output")
    successes, failures = cleaner.clean_all()

    # Should still succeed but output will be empty/minimal
    assert len(successes) + len(failures) == 1
