import pytest
from standardisation.content_list.schema import (
    ChartBlock, ChartContent,
    EquationInterlineBlock, EquationInterlineContent,
    ImageBlock, ImageContent, ImageSource,
    InlineEquation,
    ListBlock, ListContent, ListItem,
    PageFooterBlock, PageFooterContent,
    PageHeaderBlock, PageHeaderContent,
    PageFootnoteBlock, PageFootnoteContent,
    PageNumberBlock, PageNumberContent,
    ParagraphBlock, ParagraphContent,
    TableBlock, TableContent,
    TextSpan, TitleBlock, TitleContent,
)
from standardisation.content_list.filters import (
    remove_boilerplate,
    remove_figures,
    remove_latex,
    remove_references,
    remove_tables,
)

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


def make_equation_block() -> EquationInterlineBlock:
    return EquationInterlineBlock(
        type="equation_interline",
        content=EquationInterlineContent(math_content=r"E=mc^2", math_type="latex", image_source=None),
        bbox=_BBOX,
    )


def make_inline_equation(content: str = r"\alpha") -> InlineEquation:
    return InlineEquation(type="equation_inline", content=content)


def make_image_block() -> ImageBlock:
    return ImageBlock(
        type="image",
        content=ImageContent(image_source=ImageSource(path="fig1.png"), image_caption=[], image_footnote=[]),
        bbox=_BBOX,
    )


def make_chart_block() -> ChartBlock:
    return ChartBlock(
        type="chart",
        content=ChartContent(image_source=ImageSource(path="chart1.png"), chart_caption=[], chart_footnote=[]),
        bbox=_BBOX,
    )


def make_table_block() -> TableBlock:
    return TableBlock(
        type="table",
        content=TableContent(
            image_source=None, table_caption=[], table_footnote=[],
            html="<table></table>", table_nest_level=0,
        ),
        bbox=_BBOX,
    )


def make_list_block(ordered: bool = False) -> ListBlock:
    item = ListItem(item_type="text", item_content=[TextSpan(type="text", content="item")])
    return ListBlock(
        type="list",
        content=ListContent(
            list_type="items", attribute="ordered" if ordered else "unordered", list_items=[item],
        ),
        bbox=_BBOX,
    )


# ---------------------------------------------------------------------------
# remove_boilerplate
# ---------------------------------------------------------------------------

def test_remove_boilerplate_strips_page_metadata():
    header = PageHeaderBlock(type="page_header", content=PageHeaderContent(page_header_content=[]), bbox=_BBOX)
    footer = PageFooterBlock(type="page_footer", content=PageFooterContent(page_footer_content=[]), bbox=_BBOX)
    number = PageNumberBlock(type="page_number", content=PageNumberContent(page_number_content=[]), bbox=_BBOX)
    footnote = PageFootnoteBlock(type="page_footnote", content=PageFootnoteContent(page_footnote_content=[]), bbox=_BBOX)
    para = make_paragraph("body text")
    title = make_title("Introduction")

    result = remove_boilerplate([header, footer, number, footnote, para, title])

    assert all(b.type not in {"page_header", "page_footer", "page_number", "page_footnote"} for b in result)
    assert len(result) == 2
    assert result[0] is para
    assert result[1] is title


def test_remove_boilerplate_leaves_content_blocks():
    blocks = [make_paragraph("text"), make_title("Methods"), make_table_block()]
    assert remove_boilerplate(blocks) == blocks


# ---------------------------------------------------------------------------
# remove_latex
# ---------------------------------------------------------------------------

def test_remove_latex_replaces_block_equation():
    blocks = [make_equation_block()]
    result = remove_latex(blocks)
    assert len(result) == 1
    assert result[0].type == "paragraph"
    assert result[0].content.paragraph_content[0].content == "<latex_removed>"


def test_remove_latex_replaces_inline_equation_in_paragraph():
    para = ParagraphBlock(
        type="paragraph",
        content=ParagraphContent(paragraph_content=[
            TextSpan(type="text", content="See "),
            make_inline_equation(),
            TextSpan(type="text", content=" for details."),
        ]),
        bbox=_BBOX,
    )
    result = remove_latex([para])
    spans = result[0].content.paragraph_content
    assert all(isinstance(s, TextSpan) for s in spans)
    assert spans[1].content == "<latex_removed>"


def test_remove_latex_replaces_inline_equation_in_title():
    title = TitleBlock(
        type="title",
        content=TitleContent(
            title_content=[TextSpan(type="text", content="Title "), make_inline_equation()],
            level=1,
        ),
        bbox=_BBOX,
    )
    result = remove_latex([title])
    assert result[0].content.title_content[1].content == "<latex_removed>"


def test_remove_latex_replaces_inline_equation_in_list():
    item = ListItem(item_type="text", item_content=[make_inline_equation()])
    block = ListBlock(
        type="list",
        content=ListContent(list_type="items", attribute="unordered", list_items=[item]),
        bbox=_BBOX,
    )
    result = remove_latex([block])
    assert result[0].content.list_items[0].item_content[0].content == "<latex_removed>"


def test_remove_latex_passes_through_other_blocks():
    blocks = [make_paragraph("plain"), make_title("heading"), make_table_block()]
    result = remove_latex(blocks)
    assert result[0].content.paragraph_content[0].content == "plain"
    assert result[1].content.title_content[0].content == "heading"


# ---------------------------------------------------------------------------
# remove_tables
# ---------------------------------------------------------------------------

def test_remove_tables_replaces_table_block():
    blocks = [make_paragraph("before"), make_table_block(), make_paragraph("after")]
    result = remove_tables(blocks)
    assert result[1].type == "paragraph"
    assert result[1].content.paragraph_content[0].content == "<table_removed>"


def test_remove_tables_preserves_non_table_blocks():
    blocks = [make_paragraph("text"), make_title("heading")]
    assert remove_tables(blocks) == blocks


# ---------------------------------------------------------------------------
# remove_figures
# ---------------------------------------------------------------------------

def test_remove_figures_replaces_image_block():
    blocks = [make_paragraph("text"), make_image_block()]
    result = remove_figures(blocks)
    assert result[1].content.paragraph_content[0].content == "<figure_removed>"


def test_remove_figures_replaces_chart_block():
    blocks = [make_chart_block()]
    result = remove_figures(blocks)
    assert result[0].content.paragraph_content[0].content == "<figure_removed>"


def test_remove_figures_preserves_other_blocks():
    blocks = [make_paragraph("text"), make_table_block(), make_title("heading")]
    assert remove_figures(blocks) == blocks


# ---------------------------------------------------------------------------
# remove_references
# ---------------------------------------------------------------------------

def test_remove_references_drops_from_heading_onwards():
    blocks = [
        make_paragraph("intro"),
        make_title("References", level=1),
        make_paragraph("citation 1"),
    ]
    result = remove_references(blocks)
    assert len(result) == 1
    assert result[0].content.paragraph_content[0].content == "intro"


def test_remove_references_case_insensitive():
    blocks = [make_paragraph("body"), make_title("REFERENCES", level=1)]
    result = remove_references(blocks)
    assert len(result) == 1


def test_remove_references_bibliography_matched():
    blocks = [make_paragraph("body"), make_title("Bibliography", level=1), make_paragraph("ref")]
    result = remove_references(blocks)
    assert len(result) == 1


def test_remove_references_resumes_at_same_level_heading():
    blocks = [
        make_title("Results", level=1),
        make_title("References", level=1),
        make_paragraph("dropped"),
        make_title("Supplementary", level=1),
        make_paragraph("kept"),
    ]
    result = remove_references(blocks)
    texts = [b.content.title_content[0].content if b.type == "title"
             else b.content.paragraph_content[0].content for b in result]
    assert "Results" in texts
    assert "Supplementary" in texts
    assert "kept" in texts
    assert "dropped" not in texts


def test_remove_references_higher_level_heading_not_absorbed():
    blocks = [
        make_title("References", level=2),
        make_paragraph("dropped"),
        make_title("Appendix", level=1),
        make_paragraph("kept"),
    ]
    result = remove_references(blocks)
    assert any(b.type == "title" and b.content.title_content[0].content == "Appendix" for b in result)
    assert any(b.type == "paragraph" and b.content.paragraph_content[0].content == "kept" for b in result)
    assert not any(b.type == "paragraph" and b.content.paragraph_content[0].content == "dropped" for b in result)


def test_remove_references_no_references_section_unchanged():
    blocks = [make_paragraph("body"), make_title("Discussion", level=1)]
    assert remove_references(blocks) == blocks