from __future__ import annotations
import re
from standardisation.content_list.schema import (
    ChartBlock,
    ContentBlock,
    EquationInterlineBlock,
    ImageBlock,
    InlineContent,
    InlineEquation,
    ListBlock,
    ParagraphBlock,
    ParagraphContent,
    TableBlock,
    TextSpan,
    TitleBlock,
)

# Helper to define placeholder text.
def _placeholder(text: str) -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph",
        content=ParagraphContent(paragraph_content=[TextSpan(type="text", content=text)]),
        bbox=(0, 0, 0, 0),
    )

# REGEX patterns to identify reference/bibliography content blocks.
_REFERENCES_RE = re.compile(
    r"^[\s\W]*(references|bibliography|works cited|literature cited)\s*$",
    re.IGNORECASE,
)

_BOILERPLATE_TYPES = {"page_header", "page_footer", "page_number", "page_footnote", "page_aside_text"}


def remove_boilerplate(blocks: list[ContentBlock]) -> list[ContentBlock]:
    """Always-on: strip page headers, footers, numbers, footnotes and aside text."""
    return [b for b in blocks if b.type not in _BOILERPLATE_TYPES]


# Functions that remove blocks from the JSON based on Type.
def _replace_inline_latex(spans: list[InlineContent]) -> list[InlineContent]:
    """Replace any InlineEquation spans with a <latex_removed> TextSpan."""
    placeholder = TextSpan(type="text", content="<latex_removed>")
    return [placeholder if isinstance(s, InlineEquation) else s for s in spans]

def remove_latex(blocks: list[ContentBlock]) -> list[ContentBlock]:
    """Replace block equations with a <latex_removed> placeholder paragraph.
    Replace inline equations inside paragraphs, titles, and lists with a <latex_removed> text span.
    """
    result = []
    for block in blocks:
        if isinstance(block, EquationInterlineBlock):
            result.append(_placeholder("<latex_removed>"))  # block-level
        elif isinstance(block, ParagraphBlock):
            new_spans = _replace_inline_latex(block.content.paragraph_content)
            result.append(ParagraphBlock(type="paragraph", content=ParagraphContent(paragraph_content=new_spans), bbox=block.bbox))
        elif isinstance(block, TitleBlock):
            new_spans = _replace_inline_latex(block.content.title_content)
            result.append(TitleBlock(type="title", content=block.content.model_copy(update={"title_content": new_spans}), bbox=block.bbox))
        elif isinstance(block, ListBlock):
            new_items = []
            for item in block.content.list_items:
                new_item = item.model_copy(update={"item_content": _replace_inline_latex(item.item_content)})
                new_items.append(new_item)
            result.append(ListBlock(type="list", content=block.content.model_copy(update={"list_items": new_items}), bbox=block.bbox))
        else:
            result.append(block)
    return result

def remove_tables(blocks: list[ContentBlock]) -> list[ContentBlock]:
    """Replace table blocks with a <table_removed> placeholder paragraph."""
    result = []
    for block in blocks:
        if isinstance(block, TableBlock):
            result.append(_placeholder("<table_removed>"))
        else:
            result.append(block)
    return result

def remove_figures(blocks: list[ContentBlock]) -> list[ContentBlock]:
    """Replace image and chart blocks with a <figure_removed> placeholder paragraph."""
    result = []
    for block in blocks:
        if isinstance(block, (ImageBlock, ChartBlock)):
            result.append(_placeholder("<figure_removed>"))
        else:
            result.append(block)
    return result

def remove_references(blocks: list[ContentBlock]) -> list[ContentBlock]:
    """Drop the references section and everything after it until the next same-or-higher heading."""
    result = []
    skipping = False
    ref_level: int | None = None

    for block in blocks:
        if isinstance(block, TitleBlock):
            if _REFERENCES_RE.match(block.content.text):
                skipping = True
                ref_level = block.content.level
                continue
            if skipping and block.content.level <= ref_level:
                skipping = False

        if not skipping:
            result.append(block)

    return result