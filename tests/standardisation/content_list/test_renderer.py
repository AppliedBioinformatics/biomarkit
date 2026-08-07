import pytest
from pathlib import Path
from standardisation.content_list.schema import (
    ChartBlock, ChartContent,
    ImageBlock, ImageContent, ImageSource,
    InlineEquation,
    ListBlock, ListContent, ListItem,
    MiscBlock,
    ParagraphBlock, ParagraphContent,
    TableBlock, TableContent,
    TextSpan, TitleBlock, TitleContent,
)
from standardisation.content_list.renderer import render

_BBOX = (0, 0, 0, 0)


def make_paragraph(text: str) -> ParagraphBlock:
    return ParagraphBlock(
        type="paragraph",
        content=ParagraphContent(paragraph_content=[TextSpan(type="text", content=text)]),
        bbox=_BBOX,
    )


def make_title(text: str, level: int = 1) -> TitleBlock:
    return TitleBlock(
        type="title",
        content=TitleContent(title_content=[TextSpan(type="text", content=text)], level=level),
        bbox=_BBOX,
    )


def make_table(caption: str = "", html: str = "<table></table>") -> TableBlock:
    caption_spans = [TextSpan(type="text", content=caption)] if caption else []
    return TableBlock(
        type="table",
        content=TableContent(
            image_source=None, table_caption=caption_spans, table_footnote=[],
            html=html, table_nest_level=0,
        ),
        bbox=_BBOX,
    )


def make_list_block(items: list[str], ordered: bool = False) -> ListBlock:
    list_items = [
        ListItem(item_type="text", item_content=[TextSpan(type="text", content=t)])
        for t in items
    ]
    return ListBlock(
        type="list",
        content=ListContent(
            list_type="items",
            attribute="ordered" if ordered else "unordered",
            list_items=list_items,
        ),
        bbox=_BBOX,
    )


# ---------------------------------------------------------------------------
# Title rendering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("level, expected_prefix", [
    (1, "# "),
    (2, "## "),
    (3, "### "),
    (4, "#### "),
    (5, "#### "),  # level 5+ clamps to ####
])
def test_title_heading_level(level, expected_prefix):
    result = render([make_title("Heading", level=level)])
    assert result.startswith(expected_prefix)


def test_title_text_rendered():
    result = render([make_title("Methods")])
    assert "Methods" in result


# ---------------------------------------------------------------------------
# Paragraph rendering
# ---------------------------------------------------------------------------

def test_paragraph_plain_text():
    result = render([make_paragraph("Hello world")])
    assert result == "Hello world"


def test_paragraph_with_inline_equation():
    block = ParagraphBlock(
        type="paragraph",
        content=ParagraphContent(paragraph_content=[
            TextSpan(type="text", content="See "),
            InlineEquation(type="equation_inline", content=r"\alpha"),
            TextSpan(type="text", content=" above."),
        ]),
        bbox=_BBOX,
    )
    result = render([block])
    assert r"$\alpha$" in result


def test_empty_paragraph_skipped():
    result = render([make_paragraph("   ")])
    assert result == ""


def test_whitespace_only_paragraph_skipped():
    result = render([make_paragraph("\n\t")])
    assert result == ""


# ---------------------------------------------------------------------------
# Table rendering
# ---------------------------------------------------------------------------

def test_table_with_caption_and_html():
    result = render([make_table(caption="Table 1. Summary", html="<table><tr></tr></table>")])
    assert "**Table 1. Summary**" in result
    assert "<table>" in result


def test_table_without_caption_no_bold():
    result = render([make_table(caption="", html="<table></table>")])
    assert "**" not in result
    assert "<table>" in result


def test_empty_table_skipped():
    block = TableBlock(
        type="table",
        content=TableContent(
            image_source=None, table_caption=[], table_footnote=[],
            html="", table_nest_level=0,
        ),
        bbox=_BBOX,
    )
    result = render([block])
    assert result == ""


# ---------------------------------------------------------------------------
# List rendering
# ---------------------------------------------------------------------------

def test_unordered_list_uses_dash():
    result = render([make_list_block(["alpha", "beta"])])
    assert "- alpha" in result
    assert "- beta" in result


def test_ordered_list_uses_numbers():
    result = render([make_list_block(["first", "second"], ordered=True)])
    assert "1. first" in result
    assert "2. second" in result


# ---------------------------------------------------------------------------
# Multi-block joining
# ---------------------------------------------------------------------------

def test_multiple_blocks_joined_by_double_newline():
    result = render([make_title("Introduction"), make_paragraph("Body text.")])
    assert result == "# Introduction\n\nBody text."


# ---------------------------------------------------------------------------
# Unknown block types skipped
# ---------------------------------------------------------------------------

def test_misc_block_silently_skipped():
    misc = MiscBlock(type="unknown_type", content={}, bbox=_BBOX)
    result = render([misc, make_paragraph("kept")])
    assert result == "kept"


# ---------------------------------------------------------------------------
# Image rendering
# ---------------------------------------------------------------------------

def make_image(caption: str = "", path: str = "fig1.png") -> ImageBlock:
    return ImageBlock(
        type="image",
        content=ImageContent(
            image_source=ImageSource(path=path),
            image_caption=[TextSpan(type="text", content=caption)] if caption else [],
        ),
        bbox=_BBOX,
    )


def test_image_renders_markdown_link():
    result = render([make_image(caption="A figure", path="fig1.png")])
    assert "![A figure](fig1.png)" in result


def test_image_with_caption_renders_italic_caption():
    result = render([make_image(caption="My caption", path="fig.png")])
    assert "*My caption*" in result


def test_image_no_caption_no_italic():
    result = render([make_image(caption="", path="fig.png")])
    assert "*" not in result


def test_image_path_resolved_with_images_dir():
    result = render([make_image(path="fig1.png")], images_dir=Path("auto"))
    assert "auto/fig1.png" in result


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------

def make_chart(caption: str = "", path: str = "chart1.png") -> ChartBlock:
    return ChartBlock(
        type="chart",
        content=ChartContent(
            image_source=ImageSource(path=path),
            chart_caption=[TextSpan(type="text", content=caption)] if caption else [],
        ),
        bbox=_BBOX,
    )


def test_chart_renders_markdown_link():
    result = render([make_chart(caption="A chart", path="chart1.png")])
    assert "![A chart](chart1.png)" in result


def test_chart_with_caption_renders_italic():
    result = render([make_chart(caption="Chart caption", path="chart.png")])
    assert "*Chart caption*" in result


def test_chart_path_resolved_with_images_dir():
    result = render([make_chart(path="chart1.png")], images_dir=Path("auto"))
    assert "auto/chart1.png" in result