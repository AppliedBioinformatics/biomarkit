"""Normalise markdown heading text by stripping numbering, markers, and case."""
import re

_HASHES = re.compile(r"^#{1,6}\s*")
_SECTION_NUM = re.compile(r"^\.?\s*[\d]+(?:\.[\d]+)*\.?\s*")
_LEADING_DOT = re.compile(r"^\.\s+")
_PIPE_SEP = re.compile(r"^\|\s*")
_BOLD = re.compile(r"\*\*")

# Detect duplicated heading text (OCR/PDF artefact), e.g. "Results2. Results" or "Genetic Analysis2.1. Genetic Analysis"
_DUPE_SUFFIX = re.compile(r"(.{4,}?)\d+(?:\.\d+)*\.?\s*\1$", re.IGNORECASE)


def normalise_heading(heading: str) -> str:
    """Strip markdown markers, numbering, bold, and normalise to lowercase.

    Examples:
        "## 2.1. MATERIALS AND METHODS" -> "materials and methods"
        "# 1 INTRODUCTION" -> "introduction"
        "## 4.2.1 | Chromosome 4A" -> "chromosome 4a"
        "## 2. Results2. Results" -> "results"
    """
    text = _HASHES.sub("", heading)
    text = _BOLD.sub("", text)
    text = text.strip()
    text = _SECTION_NUM.sub("", text)
    text = _LEADING_DOT.sub("", text)
    text = _PIPE_SEP.sub("", text)
    text = text.strip().lower()
    # Remove duplicated suffixes from OCR/PDF artefacts
    m = _DUPE_SUFFIX.search(text)
    if m:
        text = m.group(1).strip()
    return text