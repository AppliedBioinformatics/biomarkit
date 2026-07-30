"""Assemble standardised markdown from classified heading actions."""
import re
from standardisation.text_cleaning.section_classifier import Action

_SECTION_HEADINGS = {
    Action.INTRODUCTION: "## Introduction",
    Action.METHODS: "## Methods",
    Action.RESULTS: "## Results",
    Action.DISCUSSION: "## Discussion",
}

_HEADING_RE = re.compile(r"^#{1,6}\s+")

# Subheadings within a major (##) IMRaD section are preserved one level deeper.
_SUBHEADING_LEVEL = "### "


def _as_subheading(line: str) -> str:
    """Re-level a markdown heading line to a ### subheading, preserving its text."""
    return _SUBHEADING_LEVEL + _HEADING_RE.sub("", line)


def assemble(content: str, actions: dict[int, Action]) -> str:
    """Build standardised markdown from content and per-line actions.

    Args:
        content: Original markdown content string.
        actions: {line_number (1-indexed): Action} for all classified heading lines.

    Returns:
        Standardised markdown with only Introduction/Methods/Results/Discussion sections.
    """
    if not content:
        return ""

    lines = content.split("\n")
    output_lines: list[str] = []
    current_section: Action | None = None
    in_deleted_section = False
    emitted_sections: set[Action] = set()

    major_sections = {Action.INTRODUCTION, Action.METHODS, Action.RESULTS, Action.DISCUSSION}
    first_major_line = None
    for line_num, action in sorted(actions.items()):
        if action in major_sections:
            first_major_line = line_num
            break

    if first_major_line is None:
        return ""

    for i, line in enumerate(lines):
        line_num = i + 1

        if line_num < first_major_line:
            continue

        if line_num in actions:
            action = actions[line_num]

            if action in major_sections:
                current_section = action
                in_deleted_section = False
                if action not in emitted_sections:
                    output_lines.append("")
                    output_lines.append(_SECTION_HEADINGS[action])
                    emitted_sections.add(action)
            elif action == Action.DELETE:
                in_deleted_section = True
                current_section = None
            elif action == Action.BODY:
                if not in_deleted_section:
                    # BODY actions attach to heading lines; preserve them as
                    # ### subheadings rather than flattening to plain text.
                    output_lines.append(_as_subheading(line))
        else:
            if not in_deleted_section and current_section is not None:
                if _HEADING_RE.match(line):
                    output_lines.append(_as_subheading(line))
                else:
                    output_lines.append(line)

    result = "\n".join(output_lines).strip()
    return result
