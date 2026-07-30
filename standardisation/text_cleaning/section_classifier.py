"""Regex-based section classification for research paper headings."""
import re
from enum import Enum
from typing import Optional

from standardisation.text_cleaning.heading_normaliser import normalise_heading


class Action(Enum):
    INTRODUCTION = "introduction"
    METHODS = "methods"
    RESULTS = "results"
    DISCUSSION = "discussion"
    DELETE = "delete"
    BODY = "body"


_SECTION_PATTERNS: list[tuple[re.Pattern, Action]] = [
    (re.compile(r"^(?:introduction|background|introducciÃ³n)$"), Action.INTRODUCTION),
    # Match "materials and methods" even if followed by a subsection name on same line
    (re.compile(r"^(?:materials?\s+and\s+methods?|methods?|experimental|methodology|materiales\s+y\s+mÃ©todos)(?:\s|$|[^a-z])"), Action.METHODS),
    (re.compile(r"^(?:results?\s+and\s+discussion|results?|characteristics|findings|resultados)(?:\s|$|[^a-z])"), Action.RESULTS),
    (re.compile(r"^(?:discussion|conclusions?|concluding\s+remarks?|discusiÃ³n)$"), Action.DISCUSSION),
]

_DELETE_PATTERNS: list[re.Pattern] = [
    # Abstract / front matter
    re.compile(r"^abstract$"),
    re.compile(r"^key\s*words?$"),
    re.compile(r"^abbreviations?$"),
    # References / bibliography
    re.compile(r"^references?$"),
    re.compile(r"^literature\s+cited$"),
    re.compile(r"^bibliography$"),
    # Acknowledgements / funding / ethics
    re.compile(r"^acknowledg[e]?ments?$"),
    re.compile(r"^funding.*$"),
    re.compile(r"^declarations?$"),
    re.compile(r"^ethics\s+(?:statement|approval).*$"),
    re.compile(r"^compliance\s+with\s+ethical\s+standards$"),
    re.compile(r"^consent\s+for\s+publication$"),
    re.compile(r"^ethics\s+approval\s+and\s+consent\s+to\s+participate$"),
    # Author / conflict / data
    re.compile(r"^authors?\s+contributions?$"),
    re.compile(r"^authors?\s+information$"),
    re.compile(r"^authors?\s+details?$"),
    re.compile(r"^conflicts?\s+of\s+interest$"),
    re.compile(r"^competing\s+interests?$"),
    re.compile(r"^data\s+availability.*$"),
    re.compile(r"^availability.*$"),
    re.compile(r"^code\s+availability.*$"),
    # Supplementary / supporting
    re.compile(r"^supplementary\s+(?:materials?|information|data)$"),
    re.compile(r"^supporting\s+information$"),
    re.compile(r"^additional\s+(?:information|files?)$"),
    # Publisher metadata
    re.compile(r"^orcid$"),
    re.compile(r"^publisher.*note$"),
    re.compile(r"^open\s+access$"),
    re.compile(r"^copyright.*$"),
    re.compile(r"^correspondence$"),
    re.compile(r"^core\s+ideas$"),
    re.compile(r"^citation:?$"),
    re.compile(r"^figures?$"),
    re.compile(r"^tables?$"),
    # Authorship variants
    re.compile(r"^credit\s+authorship\s+contribution\s+statement$"),
    re.compile(r"^authors?\s+(?:declaration|statement)s?$"),
    re.compile(r"^cre?dit.*$"),
    # Spaced-out OCR artefacts (e.g. "s u p p o rt i ng i n fo r m at i o n")
    re.compile(r"^[a-z]\s+[a-z]\s+[a-z]\s+.*$"),
    # Spanish equivalents
    re.compile(r"^resumen$"),
    re.compile(r"^summary$"),
    # Supplementary figures/tables (e.g. "supplementary figure 1")
    re.compile(r"^supplementary\s+(?:figure|table)\s+\d+.*$"),
    # Miscellaneous publisher boilerplate
    re.compile(r"^check\s+for\s+updates$"),
    re.compile(r"^contributed\s+equally.*$"),
    re.compile(r"^.+contributed\s+equally.*$"),
]


_SPACELESS_SECTION_PATTERNS: list[tuple[re.Pattern, Action]] = [
    (re.compile(r"^(?:introduction|background)$"), Action.INTRODUCTION),
    (re.compile(r"^(?:materialsandmethods?|methods?|experimental|methodology)"), Action.METHODS),
    (re.compile(r"^(?:resultsanddiscussion|results?|characteristics|findings)"), Action.RESULTS),
    (re.compile(r"^(?:discussion|conclusions?|concludingremarks?)$"), Action.DISCUSSION),
]

_SPACELESS_DELETE_PATTERNS: list[re.Pattern] = [
    re.compile(r"^abstract$"),
    re.compile(r"^keywords?$"),
    re.compile(r"^references?$"),
    re.compile(r"^acknowledgements?$"),
    re.compile(r"^acknowledgments?$"),
]


def classify_heading(normalised: str) -> Optional[Action]:
    """Classify a single normalised heading string.
    Returns an Action if confidently classified, None if ambiguous."""
    for pattern, action in _SECTION_PATTERNS:
        if pattern.match(normalised):
            return action
    for pattern in _DELETE_PATTERNS:
        if pattern.match(normalised):
            return Action.DELETE
    # OCR fallback: try matching with all spaces removed
    spaceless = normalised.replace(" ", "")
    if spaceless != normalised:
        for pattern, action in _SPACELESS_SECTION_PATTERNS:
            if pattern.match(spaceless):
                return action
        for pattern in _SPACELESS_DELETE_PATTERNS:
            if pattern.match(spaceless):
                return Action.DELETE
    return None


class ClassificationResult:
    """Holds classification results for a set of headings."""

    def __init__(self):
        self.actions: dict[int, Action] = {}
        self.unresolved: dict[int, str] = {}

    def __getitem__(self, line_number: int) -> Action:
        return self.actions[line_number]

    def __setitem__(self, line_number: int, action: Action):
        self.actions[line_number] = action

    def __contains__(self, line_number: int) -> bool:
        return line_number in self.actions

    def values(self):
        return self.actions.values()

    def items(self):
        return self.actions.items()


def _is_title_heading(raw_heading: str) -> bool:
    """Detect H1 headings that are paper titles (not section names)."""
    match = re.match(r"^(#{1,6})\s+", raw_heading)
    if match and len(match.group(1)) == 1:
        # Check if the H1 text is actually a known section name
        normalised = normalise_heading(raw_heading)
        if classify_heading(normalised) is not None:
            return False
        return True
    return False


def classify_headings(headings: dict[int, str]) -> ClassificationResult:
    """Classify all headings, returning resolved actions and unresolved headings."""
    result = ClassificationResult()
    for line_num, raw_heading in headings.items():
        # H1 headings are paper titles â€” always delete
        if _is_title_heading(raw_heading):
            result[line_num] = Action.DELETE
            continue
        normalised = normalise_heading(raw_heading)
        action = classify_heading(normalised)
        if action is not None:
            result[line_num] = action
        else:
            result.unresolved[line_num] = raw_heading
    return result