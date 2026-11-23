from __future__ import annotations

from pathlib import Path

from biomarkit.standardisation.content_list.schema import (
    ChartBlock,
    ContentBlock,
    EquationInterlineBlock,
    ImageBlock,
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
    footnote = _render_spans(block.content.table_footnote)
    if footnote.strip():
        parts.append(footnote)
    return "\n\n".join(parts) if parts else ""


def _render_equation(block: EquationInterlineBlock) -> str:
    math = block.content.math_content.strip()
    return f"$$\n{math}\n$$" if math else ""


def _resolve_image_path(raw: str, images_dir: Path | None) -> str:
    if not raw:
        return ""
    if images_dir is not None:
        return (images_dir / raw).as_posix()
    return raw


def _render_image(block: ImageBlock, images_dir: Path | None) -> str:
    caption = _render_spans(block.content.image_caption)
    raw = block.content.image_source.path if block.content.image_source else ""
    path = _resolve_image_path(raw, images_dir)
    # XML figures have no image file, so only the caption is rendered.
    parts = [f"![{caption}]({path})"] if path else []
    if caption:
        parts.append(f"*{caption}*")
    footnote = _render_spans(block.content.image_footnote)
    if footnote.strip():
        parts.append(footnote)
    return "\n\n".join(parts)


def _render_chart(block: ChartBlock, images_dir: Path | None) -> str:
    caption = _render_spans(block.content.chart_caption)
    raw = block.content.image_source.path if block.content.image_source else ""
    path = _resolve_image_path(raw, images_dir)
    parts = [f"![{caption}]({path})"] if path else []
    if caption:
        parts.append(f"*{caption}*")
    footnote = _render_spans(block.content.chart_footnote)
    if footnote.strip():
        parts.append(footnote)
    return "\n\n".join(parts)


def _render_list(block: ListBlock) -> str:
    lines = []
    ordered = block.content.attribute == "ordered"
    for i, item in enumerate(block.content.list_items, start=1):
        text = _render_spans(item.item_content)
        prefix = f"{i}." if ordered else "-"
        lines.append(f"{prefix} {text}")
    return "\n".join(lines)


def render(blocks: list[ContentBlock], images_dir: Path | None = None) -> str:
    """Convert a filtered list of content blocks to a markdown string.

    Parameters
    ----------
    blocks : list[ContentBlock]
        Filtered content blocks to render.
    images_dir : Path, optional
        Directory that image paths in the content-list are relative to (the
        ``auto/`` folder MinerU writes into). When provided, image paths are
        resolved to absolute so the output markdown works regardless of where
        the final .md file is saved.
    """
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
        elif isinstance(block, EquationInterlineBlock):
            text = _render_equation(block)
            if text:
                parts.append(text)
        elif isinstance(block, ImageBlock):
            text = _render_image(block, images_dir)
            if text:
                parts.append(text)
        elif isinstance(block, ChartBlock):
            text = _render_chart(block, images_dir)
            if text:
                parts.append(text)
        elif isinstance(block, ListBlock):
            parts.append(_render_list(block))

    return "\n\n".join(parts)