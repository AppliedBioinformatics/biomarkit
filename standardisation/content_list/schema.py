from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, Field

# Inline / leaf content types (nested inside block content arrays)
class TextSpan(BaseModel):
    type: Literal["text"]
    content: str


class InlineEquation(BaseModel):
    type: Literal["equation_inline"]
    content: str


InlineContent = Annotated[Union[TextSpan, InlineEquation], Field(discriminator="type")]

# Shared sub-models
class ImageSource(BaseModel):
    path: str


class ListItem(BaseModel):
    item_type: Literal["text"]
    item_content: list[InlineContent]



# Block content models
class ParagraphContent(BaseModel):
    paragraph_content: list[InlineContent]


class TitleContent(BaseModel):
    title_content: list[InlineContent]
    level: int

    @property
    def text(self) -> str:
        return "".join(span.content for span in self.title_content if isinstance(span.content, str))


class ImageContent(BaseModel):
    image_source: ImageSource
    image_caption: list[InlineContent] = Field(default_factory=list)
    image_footnote: list[InlineContent] = Field(default_factory=list)


class TableContent(BaseModel):
    image_source: ImageSource | None = None
    table_caption: list[InlineContent] = Field(default_factory=list)
    table_footnote: list[InlineContent] = Field(default_factory=list)
    html: str | None = None
    table_nest_level: int | None = None


class ChartContent(BaseModel):
    image_source: ImageSource | None = None
    chart_caption: list[InlineContent] = Field(default_factory=list)
    chart_footnote: list[InlineContent] = Field(default_factory=list)


class ListContent(BaseModel):
    list_type: str
    attribute: Literal["ordered", "unordered"] | None = None
    list_items: list[ListItem]


class EquationInterlineContent(BaseModel):
    math_content: str
    math_type: Literal["latex"]
    image_source: ImageSource | None = None


class PageHeaderContent(BaseModel):
    page_header_content: list[TextSpan]


class PageFooterContent(BaseModel):
    page_footer_content: list[TextSpan]


class PageFootnoteContent(BaseModel):
    page_footnote_content: list[TextSpan]


class PageNumberContent(BaseModel):
    page_number_content: list[TextSpan]



# Top-level block models
class ParagraphBlock(BaseModel):
    type: Literal["paragraph"]
    content: ParagraphContent
    bbox: tuple[float, float, float, float]


class TitleBlock(BaseModel):
    type: Literal["title"]
    content: TitleContent
    bbox: tuple[float, float, float, float]


class ImageBlock(BaseModel):
    type: Literal["image"]
    content: ImageContent
    bbox: tuple[float, float, float, float]


class TableBlock(BaseModel):
    type: Literal["table"]
    content: TableContent
    bbox: tuple[float, float, float, float]


class ChartBlock(BaseModel):
    type: Literal["chart"]
    content: ChartContent
    bbox: tuple[float, float, float, float]


class ListBlock(BaseModel):
    type: Literal["list"]
    content: ListContent
    bbox: tuple[float, float, float, float]


class EquationInterlineBlock(BaseModel):
    type: Literal["equation_interline"]
    content: EquationInterlineContent
    bbox: tuple[float, float, float, float]


class PageHeaderBlock(BaseModel):
    type: Literal["page_header"]
    content: PageHeaderContent
    bbox: tuple[float, float, float, float]


class PageFooterBlock(BaseModel):
    type: Literal["page_footer"]
    content: PageFooterContent
    bbox: tuple[float, float, float, float]


class PageFootnoteBlock(BaseModel):
    type: Literal["page_footnote"]
    content: PageFootnoteContent
    bbox: tuple[float, float, float, float]


class PageNumberBlock(BaseModel):
    type: Literal["page_number"]
    content: PageNumberContent
    bbox: tuple[float, float, float, float]


class MiscBlock(BaseModel):
    """Catch-all for any block type not explicitly modelled."""
    type: str
    content: Any
    bbox: tuple[float, float, float, float]



# Known types — used to route parsing
_KNOWN_BLOCK_TYPES = Annotated[
    Union[
        ParagraphBlock,
        TitleBlock,
        ImageBlock,
        TableBlock,
        ChartBlock,
        ListBlock,
        EquationInterlineBlock,
        PageHeaderBlock,
        PageFooterBlock,
        PageFootnoteBlock,
        PageNumberBlock,
    ],
    Field(discriminator="type"),
]

ContentBlock = Union[_KNOWN_BLOCK_TYPES, MiscBlock]


def _parse_block(raw: dict) -> ContentBlock:
    known = {
        "paragraph", "title", "image", "table", "chart", "list",
        "equation_interline", "page_header", "page_footer",
        "page_footnote", "page_number",
    }
    if raw.get("type") in known:
        from pydantic import TypeAdapter
        return TypeAdapter(_KNOWN_BLOCK_TYPES).validate_python(raw)
    return MiscBlock.model_validate(raw)


Page = list[ContentBlock]



# Document — top-level parsed representation of content_list_v2.json
class Document(BaseModel):
    pages: list[Page]

    @classmethod
    def from_file(cls, path: Path) -> Document:
        raw: list[list[dict]] = json.loads(path.read_text(encoding="utf-8"))
        pages = [[_parse_block(block) for block in page] for page in raw]
        return cls(pages=pages)

    def blocks(self) -> list[ContentBlock]:
        """Flat list of all blocks across all pages."""
        return [block for page in self.pages for block in page]

    def titles(self) -> list[TitleBlock]:
        return [b for b in self.blocks() if isinstance(b, TitleBlock)]

    def paragraphs(self) -> list[ParagraphBlock]:
        return [b for b in self.blocks() if isinstance(b, ParagraphBlock)]
