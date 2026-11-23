import pytest
from pathlib import Path
from biomarkit.standardisation.content_list.schema import (
    ChartBlock, ChartContent,
    EquationInterlineBlock, EquationInterlineContent,
    ImageBlock, ImageContent, ImageSource,
    InlineEquation,
    ListBlock, ListContent, ListItem,
    MiscBlock,
    ParagraphBlock, ParagraphContent,
    TableBlock, TableContent,
    TextSpan, TitleBlock, TitleContent,
)
from biomarkit.standardisation.content_list.renderer import render

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


def make_table(caption: str = "", html: str = "<table></table>", footnote: str = "") -> TableBlock:
    caption_spans = [TextSpan(type="text", content=caption)] if caption else []
    footnote_spans = [TextSpan(type="text", content=footnote)] if footnote else []
    return TableBlock(
        type="table",
        content=TableContent(
            image_source=None, table_caption=caption_spans, table_footnote=footnote_spans,
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


def test_paragraph_with_mineru4_hyperlink_and_code_spans_parsed_and_rendered_as_text():
    from biomarkit.standardisation.content_list.schema import _parse_block
    # Raw MinerU 4 V2 spans, including extra fields (style, url, children) the schema should tolerate.
    block = _parse_block({
        "type": "paragraph",
        "content": {"paragraph_content": [
            {"type": "text", "content": "Licensed under ", "style": ["italic"]},
            {"type": "hyperlink", "content": "CC BY 4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
            {"type": "text", "content": "; run "},
            {"type": "code_inline", "content": "pip install x"},
            {"type": "hyperlink", "content": "a link", "url": "https://x.org",
             "children": [{"type": "text", "content": "a "}, {"type": "text", "content": "link"}]},
        ]},
        "bbox": [0, 0, 1, 1],
    })
    assert render([block]) == "Licensed under CC BY 4.0; run pip install xa link"


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


def test_table_footnote_rendered_after_html():
    result = render([make_table(caption="Table 1", html="<table></table>", footnote="* p < 0.05")])
    assert result == "**Table 1**\n\n<table></table>\n\n* p < 0.05"


def test_table_with_only_footnote_not_dropped():
    assert render([make_table(html="", footnote="Note")]) == "Note"


# ---------------------------------------------------------------------------
# Display equation rendering
# ---------------------------------------------------------------------------

def make_equation(math: str) -> EquationInterlineBlock:
    return EquationInterlineBlock(
        type="equation_interline",
        content=EquationInterlineContent(math_content=math, math_type="latex"),
        bbox=_BBOX,
    )


def test_display_equation_rendered_in_order():
    result = render([make_paragraph("before"), make_equation(r"E=mc^2"), make_paragraph("after")])
    assert result == "before\n\n$$\nE=mc^2\n$$\n\nafter"


def test_blank_display_equation_skipped():
    assert render([make_equation("  "), make_paragraph("kept")]) == "kept"


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


def test_image_footnote_rendered():
    block = make_image(caption="Cap", path="fig.png")
    block.content.image_footnote = [TextSpan(type="text", content="Scale bar 10 µm")]
    assert render([block]).endswith("*Cap*\n\nScale bar 10 µm")


def test_image_path_resolved_with_images_dir():
    result = render([make_image(path="fig1.png")], images_dir=Path("auto"))
    assert "auto/fig1.png" in result


def test_image_without_path_renders_caption_only():
    result = render([make_image(caption="Fig. 1: Legend", path="")], images_dir=Path("auto"))
    assert result == "*Fig. 1: Legend*"


def test_image_without_path_or_caption_skipped():
    blocks = [ParagraphBlock(type="paragraph", content=ParagraphContent(paragraph_content=[TextSpan(type="text", content="Before")]), bbox=_BBOX),
              make_image(path="")]
    assert render(blocks) == "Before"


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


def test_chart_footnote_rendered():
    block = make_chart(caption="Cap", path="chart.png")
    block.content.chart_footnote = [TextSpan(type="text", content="Source: X")]
    assert render([block]).endswith("*Cap*\n\nSource: X")


def test_chart_path_resolved_with_images_dir():
    result = render([make_chart(path="chart1.png")], images_dir=Path("auto"))
    assert "auto/chart1.png" in result


def test_chart_without_path_renders_caption_only():
    assert render([make_chart(caption="Chart caption", path="")]) == "*Chart caption*"