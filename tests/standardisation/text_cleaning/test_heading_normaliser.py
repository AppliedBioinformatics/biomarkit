import pytest
from standardisation.text_cleaning.heading_normaliser import normalise_heading


@pytest.mark.parametrize("raw, expected", [
    ("## 1. Introduction", "introduction"),
    ("## 2.1. MATERIALS AND METHODS", "materials and methods"),
    ("## 3 RESULTS", "results"),
    ("# 1 INTRODUCTION", "introduction"),
    ("## Results and Discussion", "results and discussion"),
    ("## LITERATURE CITED", "literature cited"),
    ("## 4.2.1 | Chromosome 4A", "chromosome 4a"),
    ("### Plant Materials", "plant materials"),
    ("## **Abstract**", "abstract"),
    ("## Discussion", "discussion"),
    ("##   Spaced Heading  ", "spaced heading"),
])
def test_normalise_heading(raw, expected):
    assert normalise_heading(raw) == expected