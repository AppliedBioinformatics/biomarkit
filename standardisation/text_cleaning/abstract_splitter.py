"""Detect and split merged abstract+introduction sections."""
import logging
import re
from difflib import SequenceMatcher

from standardisation.text_cleaning.section_classifier import Action, ClassificationResult


def _normalise_for_comparison(text: str) -> str:
    """Collapse whitespace and strip for fuzzy comparison."""
    return re.sub(r"\s+", " ", text).strip().lower()


def find_intro_after_abstract(
    lines: list[str],
    classification: ClassificationResult,
    known_abstract: str,
    similarity_threshold: float = 0.6,
) -> int | None:
    """Find the line where introduction text begins after a merged abstract.

    Args:
        lines: Document lines (0-indexed list).
        classification: Current heading classification result.
        known_abstract: The abstract text from Publication.abstract.
        similarity_threshold: Minimum SequenceMatcher ratio to consider
            accumulated text as matching the abstract.

    Returns:
        1-indexed line number where the introduction starts, or None
        if no split point is found.
    """
    # Check preconditions: no Introduction found, Abstract heading exists
    has_intro = any(
        a == Action.INTRODUCTION for a in classification.actions.values()
    )
    if has_intro:
        return None

    # Find the Abstract heading line
    abstract_line = None
    for line_num, action in sorted(classification.actions.items()):
        if action == Action.DELETE:
            # Check if this is actually the abstract heading
            heading_text = lines[line_num - 1] if line_num - 1 < len(lines) else ""
            normalised = re.sub(r"^#{1,6}\s*", "", heading_text).strip().lower()
            if normalised == "abstract":
                abstract_line = line_num
                break

    if abstract_line is None:
        return None

    # Find the next heading after the abstract
    next_heading_line = None
    heading_lines = sorted(classification.actions.keys())
    for hl in heading_lines:
        if hl > abstract_line:
            next_heading_line = hl
            break

    if next_heading_line is None:
        # Abstract is the last heading -- no content to split
        return None

    # Collect body text between abstract heading and next heading
    norm_abstract = _normalise_for_comparison(known_abstract)

    # Accumulate lines after the abstract heading, tracking where the
    # known abstract text ends
    accumulated = ""
    best_ratio = 0.0
    best_split_line = None

    for i in range(abstract_line, next_heading_line - 1):  # 1-indexed to 0-indexed
        line_idx = i  # lines list is 0-indexed, line numbers are 1-indexed
        if line_idx >= len(lines):
            break

        line_text = lines[line_idx].strip()
        if not line_text:
            continue  # skip blank lines

        # Skip heading lines
        if re.match(r"^#{1,6}\s+", lines[line_idx]):
            continue

        accumulated += " " + line_text
        norm_accumulated = _normalise_for_comparison(accumulated)

        ratio = SequenceMatcher(None, norm_abstract, norm_accumulated).ratio()

        if ratio >= best_ratio:
            best_ratio = ratio
            best_split_line = i + 2  # next line after this one (1-indexed)
        elif ratio < best_ratio - 0.1:
            # Ratio dropping significantly -- we've passed the abstract
            break

    if best_ratio >= similarity_threshold and best_split_line is not None:
        # Make sure split line is before the next heading and there's content after
        if best_split_line < next_heading_line:
            # Check there's actual non-empty content between split and next heading
            has_content = any(
                lines[j].strip()
                for j in range(best_split_line - 1, next_heading_line - 1)
                if j < len(lines) and not re.match(r"^#{1,6}\s+", lines[j])
            )
            if has_content:
                logging.info(
                    f"Abstract-intro split: abstract ends at line {best_split_line - 1}, "
                    f"introduction starts at line {best_split_line} "
                    f"(similarity={best_ratio:.2f})"
                )
                return best_split_line

    return None
