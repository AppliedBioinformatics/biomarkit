import pytest
from biomarkit.standardisation.content_list.schema import (
    ChartBlock, ChartContent,
    EquationInterlineBlock, EquationInterlineContent,
    ImageBlock, ImageContent, ImageSource,
    InlineEquation,
    ListBlock, ListContent, ListItem,
    PageFooterBlock, PageFooterContent,
    PageHeaderBlock, PageHeaderContent,
    PageFootnoteBlock, PageFootnoteContent,
    PageNumberBlock, PageNumberContent,
    PageAsideTextBlock, PageAsideTextContent,
    ParagraphBlock, ParagraphContent,
    TableBlock, TableContent,
    TextSpan, TitleBlock, TitleContent,
)
from biomarkit.standardisation.content_list.filters import (
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
    aside = PageAsideTextBlock(type="page_aside_text", content=PageAsideTextContent(page_aside_text_content=[]),
                               bbox=_BBOX)
    para = make_paragraph("body text")
    title = make_title("Introduction")

    result = remove_boilerplate([header, footer, number, footnote, aside, para, title])

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

def make_reference_list() -> ListBlock:
    item = ListItem(item_type="text", item_content=[TextSpan(type="text", content="Smith J. A paper. 2020.")])
    return ListBlock(type="list", content=ListContent(list_type="reference_list", list_items=[item]), bbox=_BBOX)


def _texts(blocks) -> list[str]:
    return [b.content.title_content[0].content if b.type == "title" else b.content.paragraph_content[0].content
            for b in blocks if b.type in ("title", "paragraph")]


def test_remove_references_replaces_reference_list():
    result = remove_references([make_title("References"), make_reference_list()])
    assert _texts(result) == ["References", "<references_removed>"]


def test_remove_references_keeps_text_lists():
    blocks = [make_paragraph("body"), make_list_block()]
    assert remove_references(blocks) == blocks


def test_remove_references_does_not_truncate_following_sections():
    # Nature-style order: Methods after References, at a lower heading level than References.
    blocks = [
        make_title("Discussion", level=1), make_paragraph("discussion"),
        make_title("References", level=1), make_reference_list(),
        make_title("Methods", level=2), make_paragraph("methods"),
    ]
    assert _texts(remove_references(blocks)) == [
        "Discussion", "discussion", "References", "<references_removed>", "Methods", "methods"]


def test_remove_references_untyped_entries_left_in_place():
    blocks = [make_paragraph("body"), make_title("References"), make_paragraph("Smith J. A paper. 2020.")]
    assert remove_references(blocks) == blocks


# ---------------------------------------------------------------------------
# Removed blocks leave only the placeholder in rendered output
# ---------------------------------------------------------------------------

def test_remove_tables_drops_caption_and_footnote_from_render():
    from biomarkit.standardisation.content_list.renderer import render
    table = TableBlock(
        type="table",
        content=TableContent(
            table_caption=[TextSpan(type="text", content="Table 1")],
            table_footnote=[TextSpan(type="text", content="* p < 0.05")],
            html="<table></table>",
        ),
        bbox=_BBOX,
    )
    assert render(remove_tables([table])) == "<table_removed>"


def test_remove_figures_drops_footnote_from_render():
    from biomarkit.standardisation.content_list.renderer import render
    image = make_image_block()
    image.content.image_footnote = [TextSpan(type="text", content="Scale bar")]
    assert render(remove_figures([image])) == "<figure_removed>"


def test_remove_latex_display_equation_renders_placeholder():
    from biomarkit.standardisation.content_list.renderer import render
    assert render(remove_latex([make_equation_block()])) == "<latex_removed>"
