from __future__ import annotations

from standardisation.content_list.schema import (
    ContentBlock,
    InlineEquation,
    ListBlock,
    ParagraphBlock,
    TableBlock,
    TitleBlock,
)

_LEVEL_TO_HASHES = {1: "#", 2: "##", 3: "###", 4: "####"}


def _render_spans(spans) -> str:
    parts = []
    for s in spans:
        if isinstance(s, InlineEquation):
            parts.append(f"${s.content}$")
        else:
            parts.append(s.content)
    return "".join(parts)


def _render_title(block: TitleBlock) -> str:
    hashes = _LEVEL_TO_HASHES.get(block.content.level, "####")
    return f"{hashes} {_render_spans(block.content.title_content)}"


def _render_paragraph(block: ParagraphBlock) -> str:
    return _render_spans(block.content.paragraph_content)


def _render_table(block: TableBlock) -> str:
    parts = []
    caption = _render_spans(block.content.table_caption)
    if caption:
        parts.append(f"**{caption}**")
    if block.content.html:
        parts.append(block.content.html)
    return "\n\n".join(parts) if parts else ""


def _render_list(block: ListBlock) -> str:
    lines = []
    ordered = block.content.attribute == "ordered"
    for i, item in enumerate(block.content.list_items, start=1):
        text = _render_spans(item.item_content)
        prefix = f"{i}." if ordered else "-"
        lines.append(f"{prefix} {text}")
    return "\n".join(lines)


def render(blocks: list[ContentBlock]) -> str:
    """Convert a filtered list of content blocks to a markdown string."""
    parts = []
    for block in blocks:
        if isinstance(block, TitleBlock):
            parts.append(_render_title(block))
        elif isinstance(block, ParagraphBlock):
            text = _render_paragraph(block)
            if text.strip():
                parts.append(text)
        elif isinstance(block, TableBlock):
            text = _render_table(block)
            if text:
                parts.append(text)
        elif isinstance(block, ListBlock):
            parts.append(_render_list(block))

    return "\n\n".join(parts)