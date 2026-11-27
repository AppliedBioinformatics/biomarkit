import json
import xml.etree.ElementTree as ET
from pathlib import Path
from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_transformation.converters.elsevier2json import (
    ElsevierXmlTransformer,
    clean_text,
    get_element_text,
    extract_title,
    extract_abstract,
    extract_references,
    _parse_mathml,
    _spans,
    _para_block,
    _title_block,
    _table_block,
    _figure_block,
    _extract_formula,
    _enhance_text_formulas,
    parse_elsevier_xml_to_blocks,
)

CE = "http://www.elsevier.com/xml/common/dtd"
JA = "http://www.elsevier.com/xml/ja/dtd"
DEFAULT_NS = "http://www.elsevier.com/xml/svapi/article/dtd"

_MINIMAL_XML = (
    '<?xml version="1.0"?>'
    '<full-text-retrieval-response xmlns="http://www.elsevier.com/xml/svapi/article/dtd">'
    '<coredata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Test Title</dc:title></coredata>'
    '</full-text-retrieval-response>'
)


def _root(xml_str):
    return ET.fromstring(xml_str)


def _article_xml(title="My Paper", author_given="John", author_surname="Doe",
                 abstract_text="Abstract text.", keywords=None):
    kw_block = ""
    if keywords:
        kw_items = "".join(
            f'<ce:keyword xmlns:ce="{CE}"><ce:text xmlns:ce="{CE}">{k}</ce:text></ce:keyword>'
            for k in keywords
        )
        kw_block = f'<ce:keywords xmlns:ce="{CE}" class="keyword">{kw_items}</ce:keywords>'
    return (
        f'<?xml version="1.0"?>'
        f'<full-text-retrieval-response xmlns="{DEFAULT_NS}">'
        f'<ja:article xmlns:ja="{JA}">'
        f'<ja:head xmlns:ja="{JA}">'
        f'<ce:title xmlns:ce="{CE}">{title}</ce:title>'
        f'<ce:author-group xmlns:ce="{CE}">'
        f'<ce:author xmlns:ce="{CE}">'
        f'<ce:given-name xmlns:ce="{CE}">{author_given}</ce:given-name>'
        f'<ce:surname xmlns:ce="{CE}">{author_surname}</ce:surname>'
        f'</ce:author>'
        f'</ce:author-group>'
        f'<ce:abstract xmlns:ce="{CE}">'
        f'<ce:abstract-sec xmlns:ce="{CE}">'
        f'<ce:simple-para xmlns:ce="{CE}">{abstract_text}</ce:simple-para>'
        f'</ce:abstract-sec>'
        f'</ce:abstract>'
        f'{kw_block}'
        f'</ja:head>'
        f'</ja:article>'
        f'</full-text-retrieval-response>'
    )


# ---------------------------------------------------------------------------
# clean_text
# ---------------------------------------------------------------------------

def test_clean_text_collapses_whitespace():
    assert clean_text("  hello   world  ") == "hello world"


def test_clean_text_empty_string():
    assert clean_text("") == ""


def test_clean_text_newlines_collapsed():
    assert clean_text("line1\n  line2") == "line1 line2"


# ---------------------------------------------------------------------------
# get_element_text
# ---------------------------------------------------------------------------

def test_get_element_text_plain():
    elem = ET.fromstring(f'<ce:para xmlns:ce="{CE}">Hello world</ce:para>')
    assert get_element_text(elem) == "Hello world"


def test_get_element_text_bold():
    elem = ET.fromstring(f'<ce:para xmlns:ce="{CE}"><ce:bold xmlns:ce="{CE}">strong</ce:bold></ce:para>')
    assert "**strong**" in get_element_text(elem)


def test_get_element_text_italic():
    elem = ET.fromstring(f'<ce:para xmlns:ce="{CE}"><ce:italic xmlns:ce="{CE}">emph</ce:italic></ce:para>')
    assert "_emph_" in get_element_text(elem)


def test_get_element_text_sup():
    elem = ET.fromstring(f'<ce:para xmlns:ce="{CE}">x<ce:sup xmlns:ce="{CE}">2</ce:sup></ce:para>')
    assert "^2^" in get_element_text(elem)


def test_get_element_text_tail_preserved():
    elem = ET.fromstring(f'<ce:para xmlns:ce="{CE}"><ce:bold xmlns:ce="{CE}">B</ce:bold> tail</ce:para>')
    assert "tail" in get_element_text(elem)


# ---------------------------------------------------------------------------
# extract_title
# ---------------------------------------------------------------------------

def test_extract_title_from_article_head():
    root = _root(_article_xml(title="My Great Paper"))
    assert extract_title(root) == "My Great Paper"


def test_extract_title_fallback_coredata():
    root = _root(_MINIMAL_XML)
    assert extract_title(root) == "Test Title"


def test_extract_title_missing_returns_empty():
    root = _root(f'<full-text-retrieval-response xmlns="{DEFAULT_NS}"/>')
    assert extract_title(root) == ""


# ---------------------------------------------------------------------------
# extract_abstract
# ---------------------------------------------------------------------------

def test_extract_abstract_text():
    root = _root(_article_xml(abstract_text="This is the abstract."))
    assert extract_abstract(root) == "This is the abstract."


def test_extract_abstract_missing_returns_empty():
    root = _root(_MINIMAL_XML)
    assert extract_abstract(root) == ""


# ---------------------------------------------------------------------------
# _parse_mathml
# ---------------------------------------------------------------------------

def test_parse_mathml_mi():
    MML = "http://www.w3.org/1998/Math/MathML"
    elem = ET.fromstring(f'<mi xmlns="{MML}">x</mi>')
    assert _parse_mathml(elem) == "x"


def test_parse_mathml_msup():
    MML = "http://www.w3.org/1998/Math/MathML"
    xml = f'<msup xmlns="{MML}"><mi>x</mi><mn>2</mn></msup>'
    result = _parse_mathml(ET.fromstring(xml))
    assert "x" in result and "2" in result


def test_parse_mathml_mfrac():
    MML = "http://www.w3.org/1998/Math/MathML"
    xml = f'<mfrac xmlns="{MML}"><mn>1</mn><mn>2</mn></mfrac>'
    assert r"\frac" in _parse_mathml(ET.fromstring(xml))


def test_parse_mathml_greek_symbol_converted():
    MML = "http://www.w3.org/1998/Math/MathML"
    elem = ET.fromstring(f'<mi xmlns="{MML}">α</mi>')
    assert r"\alpha" in _parse_mathml(elem)


# ---------------------------------------------------------------------------
# extract_references
# ---------------------------------------------------------------------------

def test_extract_references_source_text():
    xml = (
        f'<root xmlns:ce="{CE}">'
        f'<ce:bib-reference xmlns:ce="{CE}">'
        f'<ce:other-ref xmlns:ce="{CE}">'
        f'<ce:source-text xmlns:ce="{CE}">Doe J. (2020). A paper. Nature.</ce:source-text>'
        f'</ce:other-ref>'
        f'</ce:bib-reference>'
        f'</root>'
    )
    refs = extract_references(ET.fromstring(xml))
    assert len(refs) == 1
    assert "Doe J." in refs[0]


def test_extract_references_empty_when_none():
    xml = f'<root xmlns:ce="{CE}"/>'
    assert extract_references(ET.fromstring(xml)) == []


def test_parse_references_emitted_as_reference_list(tmp_path):
    bib = (f'<ce:bib-reference xmlns:ce="{CE}"><ce:other-ref xmlns:ce="{CE}">'
           f'<ce:source-text xmlns:ce="{CE}">Doe J. (2020). A paper. Nature.</ce:source-text>'
           f'</ce:other-ref></ce:bib-reference>')
    xml_path = tmp_path / "refs.xml"
    xml_path.write_text(_article_xml().replace("</ja:head>", f"</ja:head>{bib}"), encoding="utf-8")
    blocks = parse_elsevier_xml_to_blocks(str(xml_path))[0]

    ref_lists = [b for b in blocks if b["type"] == "list" and b["content"]["list_type"] == "reference_list"]
    assert len(ref_lists) == 1
    assert "Doe J." in ref_lists[0]["content"]["list_items"][0]["item_content"][0]["content"]
    assert not any(b["type"] == "paragraph" and "Doe J." in str(b) for b in blocks)


# ---------------------------------------------------------------------------
# ElsevierXmlTransformer.transform2json
# ---------------------------------------------------------------------------

def test_convert_creates_stem_subdirectory(tmp_path):
    xml_path = tmp_path / "elsevier_1234567890.xml"
    xml_path.write_text(_MINIMAL_XML, encoding="utf-8")

    pub = Publication(
        doi="10.1016/test",
        title="Test",
        publisher="Elsevier",
        year=2020,
        publication_filepath=xml_path,
    )
    converter = ElsevierXmlTransformer(publication_list=[pub])
    converter.output_dir = tmp_path
    result = converter.transform2json(pub)

    stem = xml_path.stem
    expected = tmp_path / stem / "auto" / f"{stem}_content_list_v2.json"
    assert result == expected
    assert expected.exists()
    assert expected.parent.is_dir()


def test_transform2json_output_is_valid_json(tmp_path):
    xml_path = tmp_path / "elsevier_test.xml"
    xml_path.write_text(_article_xml(title="JSON Test", abstract_text="Para one."), encoding="utf-8")

    pub = Publication(
        doi="10.1016/json-test",
        title="JSON Test",
        publisher="Elsevier",
        year=2021,
        publication_filepath=xml_path,
    )
    converter = ElsevierXmlTransformer(publication_list=[pub])
    converter.output_dir = tmp_path
    result_path = converter.transform2json(pub)
    data = json.loads(result_path.read_text(encoding="utf-8"))

    assert isinstance(data, list)
    assert isinstance(data[0], list)


def test_transform2json_title_block_present(tmp_path):
    xml_path = tmp_path / "elsevier_titled.xml"
    xml_path.write_text(_article_xml(title="Title Check"), encoding="utf-8")

    pub = Publication(
        doi="10.1016/title-check",
        title="Title Check",
        publisher="Elsevier",
        year=2022,
        publication_filepath=xml_path,
    )
    converter = ElsevierXmlTransformer(publication_list=[pub])
    converter.output_dir = tmp_path
    result_path = converter.transform2json(pub)
    blocks = json.loads(result_path.read_text(encoding="utf-8"))[0]

    assert any("Title Check" in str(b) for b in blocks if b.get("type") == "title")


# ---------------------------------------------------------------------------
# _spans
# ---------------------------------------------------------------------------

def test_spans_plain_text():
    result = _spans("hello world")
    assert result == [{"type": "text", "content": "hello world"}]


def test_spans_inline_equation():
    result = _spans("See $x^2$ above")
    types = [s["type"] for s in result]
    assert "equation_inline" in types
    eq = next(s for s in result if s["type"] == "equation_inline")
    assert eq["content"] == "x^2"


def test_spans_empty_string():
    result = _spans("")
    assert result == [{"type": "text", "content": ""}]


def test_spans_multiple_equations():
    result = _spans("$a$ and $b$")
    eq_spans = [s for s in result if s["type"] == "equation_inline"]
    assert len(eq_spans) == 2


# ---------------------------------------------------------------------------
# _para_block / _title_block
# ---------------------------------------------------------------------------

def test_para_block_structure():
    block = _para_block("Some text")
    assert block["type"] == "paragraph"
    assert block["content"]["paragraph_content"][0]["content"] == "Some text"


def test_title_block_structure():
    block = _title_block("Introduction", level=1)
    assert block["type"] == "title"
    assert block["content"]["level"] == 1
    assert block["content"]["title_content"][0]["content"] == "Introduction"


# ---------------------------------------------------------------------------
# _table_block
# ---------------------------------------------------------------------------

def test_table_block_returns_none_when_empty():
    xml = f'<ce:table xmlns:ce="{CE}"/>'
    assert _table_block(ET.fromstring(xml)) is None


def test_table_block_with_caption():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<ce:label xmlns:ce="{CE}">Table 1</ce:label>'
        f'<ce:caption xmlns:ce="{CE}">'
        f'<ce:simple-para xmlns:ce="{CE}">A caption</ce:simple-para>'
        f'</ce:caption>'
        f'</ce:table>'
    )
    block = _table_block(ET.fromstring(xml))
    assert block is not None
    assert block["type"] == "table"
    assert any("A caption" in s["content"] for s in block["content"]["table_caption"])


def test_table_block_joins_all_caption_paragraphs_with_label():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<ce:label>Table 2</ce:label>'
        f'<ce:caption><ce:simple-para>First part.</ce:simple-para><ce:simple-para>Second part.</ce:simple-para></ce:caption>'
        f'</ce:table>'
    )
    caption = _table_block(ET.fromstring(xml))["content"]["table_caption"]
    assert "".join(s["content"] for s in caption) == "Table 2: First part. Second part."


def test_table_block_with_rows_generates_html():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<ce:label xmlns:ce="{CE}">T1</ce:label>'
        f'<ce:caption xmlns:ce="{CE}">'
        f'<ce:simple-para xmlns:ce="{CE}">Cap</ce:simple-para>'
        f'</ce:caption>'
        f'<tgroup>'
        f'<thead><row><entry>A</entry><entry>B</entry></row></thead>'
        f'<tbody><row><entry>1</entry><entry>2</entry></row></tbody>'
        f'</tgroup>'
        f'</ce:table>'
    )
    block = _table_block(ET.fromstring(xml))
    assert block["content"]["html"] is not None
    assert "<table>" in block["content"]["html"]
    assert "<th>A</th>" in block["content"]["html"]


def test_table_block_extracts_footnotes_and_legend():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<ce:caption><ce:simple-para>Cap</ce:simple-para></ce:caption>'
        f'<ce:table-footnote><ce:label>a</ce:label><ce:note-para>Mean of three replicates.</ce:note-para></ce:table-footnote>'
        f'<ce:legend><ce:simple-para>SD, standard deviation.</ce:simple-para></ce:legend>'
        f'</ce:table>'
    )
    footnote = _table_block(ET.fromstring(xml))["content"]["table_footnote"]
    text = "".join(s["content"] for s in footnote)
    assert text == "a Mean of three replicates. SD, standard deviation."


def test_table_block_without_footnotes_has_empty_footnote():
    xml = f'<ce:table xmlns:ce="{CE}"><ce:caption><ce:simple-para>Cap</ce:simple-para></ce:caption></ce:table>'
    assert _table_block(ET.fromstring(xml))["content"]["table_footnote"] == []


# ---------------------------------------------------------------------------
# _figure_block
# ---------------------------------------------------------------------------

def test_figure_block_returns_none_without_caption():
    xml = f'<ce:figure xmlns:ce="{CE}"><ce:label>Fig. 1</ce:label><ce:link locator="gr1"/></ce:figure>'
    assert _figure_block(ET.fromstring(xml)) is None


def test_figure_block_joins_all_caption_paragraphs_with_label():
    xml = (
        f'<ce:figure xmlns:ce="{CE}">'
        f'<ce:label>Fig. 1</ce:label>'
        f'<ce:caption><ce:simple-para>First part.</ce:simple-para><ce:simple-para>Second part.</ce:simple-para></ce:caption>'
        f'<ce:link locator="gr1"/>'
        f'</ce:figure>'
    )
    block = _figure_block(ET.fromstring(xml))
    assert block["type"] == "image"
    assert block["content"]["image_source"] == {"path": ""}
    assert "".join(s["content"] for s in block["content"]["image_caption"]) == "Fig. 1: First part. Second part."
    assert block["content"]["image_footnote"] == []


def test_figure_block_extracts_legend_as_footnote():
    xml = (
        f'<ce:figure xmlns:ce="{CE}">'
        f'<ce:caption><ce:simple-para>Cap</ce:simple-para></ce:caption>'
        f'<ce:legend><ce:simple-para>Scale bar, 10 µm.</ce:simple-para></ce:legend>'
        f'</ce:figure>'
    )
    footnote = _figure_block(ET.fromstring(xml))["content"]["image_footnote"]
    assert "".join(s["content"] for s in footnote) == "Scale bar, 10 µm."


# ---------------------------------------------------------------------------
# parse_elsevier_xml_to_blocks
# ---------------------------------------------------------------------------

def test_parse_elsevier_xml_to_blocks_includes_figures(tmp_path):
    xml = (
        f'<?xml version="1.0"?>'
        f'<full-text-retrieval-response xmlns="{DEFAULT_NS}">'
        f'<ja:article xmlns:ja="{JA}">'
        f'<ja:head xmlns:ja="{JA}"><ce:title xmlns:ce="{CE}">T</ce:title></ja:head>'
        f'<ja:body xmlns:ja="{JA}">'
        f'<ce:sections xmlns:ce="{CE}">'
        f'<ce:section><ce:section-title>Results</ce:section-title>'
        f'<ce:figure><ce:caption><ce:simple-para>Inline legend.</ce:simple-para></ce:caption></ce:figure>'
        f'</ce:section>'
        f'</ce:sections>'
        f'</ja:body>'
        f'<ce:floats xmlns:ce="{CE}">'
        f'<ce:figure><ce:caption><ce:simple-para>Float legend.</ce:simple-para></ce:caption></ce:figure>'
        f'</ce:floats>'
        f'</ja:article>'
        f'</full-text-retrieval-response>'
    )
    xml_path = tmp_path / "figs.xml"
    xml_path.write_text(xml, encoding="utf-8")
    images = [b for b in parse_elsevier_xml_to_blocks(str(xml_path))[0] if b["type"] == "image"]
    captions = ["".join(s["content"] for s in b["content"]["image_caption"]) for b in images]
    assert captions == ["Inline legend.", "Float legend."]


def test_parse_elsevier_xml_to_blocks_returns_single_page(tmp_path):
    xml_path = tmp_path / "article.xml"
    xml_path.write_text(_article_xml(title="Block Test"), encoding="utf-8")
    result = parse_elsevier_xml_to_blocks(str(xml_path))
    assert isinstance(result, list)
    assert len(result) == 1  # single page
    assert isinstance(result[0], list)


def test_parse_elsevier_xml_to_blocks_contains_title(tmp_path):
    xml_path = tmp_path / "article.xml"
    xml_path.write_text(_article_xml(title="My Title"), encoding="utf-8")
    blocks = parse_elsevier_xml_to_blocks(str(xml_path))[0]
    title_blocks = [b for b in blocks if b.get("type") == "title"]
    assert any("My Title" in str(b) for b in title_blocks)


def test_parse_elsevier_xml_to_blocks_contains_abstract(tmp_path):
    xml_path = tmp_path / "article.xml"
    xml_path.write_text(_article_xml(abstract_text="The abstract text."), encoding="utf-8")
    blocks = parse_elsevier_xml_to_blocks(str(xml_path))[0]
    para_blocks = [b for b in blocks if b.get("type") == "paragraph"]
    assert any("The abstract text." in str(b) for b in para_blocks)


def test_parse_elsevier_xml_to_blocks_body_sections(tmp_path):
    xml = (
        f'<?xml version="1.0"?>'
        f'<full-text-retrieval-response xmlns="{DEFAULT_NS}">'
        f'<ja:article xmlns:ja="{JA}">'
        f'<ja:head xmlns:ja="{JA}"><ce:title xmlns:ce="{CE}">T</ce:title></ja:head>'
        f'<ja:body xmlns:ja="{JA}">'
        f'<ce:sections xmlns:ce="{CE}">'
        f'<ce:section xmlns:ce="{CE}">'
        f'<ce:section-title xmlns:ce="{CE}">Methods</ce:section-title>'
        f'<ce:para xmlns:ce="{CE}">We did things.</ce:para>'
        f'</ce:section>'
        f'</ce:sections>'
        f'</ja:body>'
        f'</ja:article>'
        f'</full-text-retrieval-response>'
    )
    xml_path = tmp_path / "body.xml"
    xml_path.write_text(xml, encoding="utf-8")
    blocks = parse_elsevier_xml_to_blocks(str(xml_path))[0]
    assert any("Methods" in str(b) for b in blocks)
    assert any("We did things." in str(b) for b in blocks)


# ---------------------------------------------------------------------------
# HTML escaping and plain-text formulas
# ---------------------------------------------------------------------------

def test_table_block_escapes_html_in_cells():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<tgroup><tbody><row><entry>a&lt;b &amp; c|d</entry></row></tbody></tgroup>'
        f'</ce:table>'
    )
    html = _table_block(ET.fromstring(xml))["content"]["html"]
    assert "<td>a&lt;b &amp; c|d</td>" in html
    assert "\|" not in html


def test_enhance_text_formulas_no_delimiters():
    assert _enhance_text_formulas("beta = alpha / 2") == r"\beta = \alpha / 2"
    assert _enhance_text_formulas("S = 1 - Σ p_i^2") == r"S = 1 - \Sigma p_{i}^2"


def test_extract_formula_plain_text_single_wrap():
    elem = ET.fromstring(f'<ce:formula xmlns:ce="{CE}">beta = alpha / 2</ce:formula>')
    formula = _extract_formula(elem)
    assert formula == r"$\beta = \alpha / 2$"
    spans = _spans(f"Plain formula {formula} here.")
    assert [s["type"] for s in spans].count("equation_inline") == 1


def test_extract_formula_display_plain_text():
    formula = _extract_formula(ET.fromstring(f'<ce:display xmlns:ce="{CE}">x = 1</ce:display>'))
    assert formula.startswith("$$\n") and formula.endswith("\n$$")


def test_extract_formula_empty_returns_empty():
    assert _extract_formula(ET.fromstring(f'<ce:formula xmlns:ce="{CE}"/>')) == ""


def test_display_formula_in_para_becomes_equation_block():
    from biomarkit.text_transformation.converters.elsevier2json import _section_to_blocks
    section = ET.fromstring(
        f'<ce:section xmlns:ce="{CE}"><ce:para>The formula is as follows: '
        f'<ce:display><ce:formula>x = 1</ce:formula></ce:display> Where x is the cost of $5.</ce:para></ce:section>'
    )
    blocks = _section_to_blocks(section)

    assert [b["type"] for b in blocks] == ["paragraph", "equation_interline", "paragraph"]
    assert blocks[1]["content"]["math_content"] == "x = 1"
    assert blocks[0]["content"]["paragraph_content"] == [{"type": "text", "content": "The formula is as follows:"}]
    assert blocks[2]["content"]["paragraph_content"][0]["content"].startswith("Where x")


def test_display_formula_outside_paragraph_becomes_inline_maths():
    from biomarkit.text_transformation.converters.elsevier2json import _parse_cals_row
    row = ET.fromstring(f'<row xmlns:ce="{CE}"><entry><ce:display><ce:formula>y = 2</ce:formula></ce:display></entry></row>')
    assert _parse_cals_row(row) == ["$y = 2$"]
    spans = _spans(f"Caption {chr(0xE000)}z = 3{chr(0xE001)} end")
    assert [s["type"] for s in spans] == ["text", "equation_inline", "text"]


# ---------------------------------------------------------------------------
# ElsevierXmlTransformer.transform_all (serial and process pool)
# ---------------------------------------------------------------------------

def _xml_pubs_with_cache(tmp_path, xml_texts):
    """Writes one XML per entry, inserts a cache row for each, and returns (publications, db_path)."""
    from biomarkit.text_download.database.database import create_database, insert_row
    db = tmp_path / "cache.sqlite"
    create_database(db)
    pubs = []
    for i, text in enumerate(xml_texts):
        xml_path = tmp_path / f"elsevier_{i:010d}.xml"
        xml_path.write_text(text, encoding="utf-8")
        doi = f"10.1016/test.{i}"
        insert_row(doi=doi, downloaded_from="elsevier", publication_filepath=str(xml_path), db_path=db)
        pubs.append(Publication(doi=doi, title=f"T{i}", publisher="elsevier", year=2020,
                                publication_filepath=xml_path, document_type="XML"))
    return pubs, db


def _make_transformer(pubs, db, tmp_path, max_workers):
    converter = ElsevierXmlTransformer(publication_list=pubs, max_workers=max_workers)
    converter.cache = db
    converter.output_dir = tmp_path / "out"
    return converter


def test_transform_all_serial_when_max_workers_1(tmp_path):
    from biomarkit.text_download.database.database import get_row_for_doi
    pubs, db = _xml_pubs_with_cache(tmp_path, [_article_xml(title="T0"), _article_xml(title="T1")])
    _make_transformer(pubs, db, tmp_path, max_workers=1).transform_all()

    for pub in pubs:
        assert pub.content_json_filepath is not None
        assert get_row_for_doi(pub.doi, db)["content_json_filepath"] is not None


def test_transform_all_parallel_two_workers(tmp_path):
    from biomarkit.text_download.database.database import get_row_for_doi
    pubs, db = _xml_pubs_with_cache(tmp_path, [_article_xml(title="Good A"), "<unclosed>", _article_xml(title="Good B")])
    _make_transformer(pubs, db, tmp_path, max_workers=2).transform_all()

    for pub, title in ((pubs[0], "Good A"), (pubs[2], "Good B")):
        assert pub.content_json_filepath is not None
        assert title in pub.content_json_filepath.read_text(encoding="utf-8")
        assert get_row_for_doi(pub.doi, db)["content_json_filepath"] is not None

    assert pubs[1].content_json_filepath is None
    assert get_row_for_doi(pubs[1].doi, db)["content_json_filepath"] is None


def test_transform_all_parallel_skips_already_converted(tmp_path):
    pubs, db = _xml_pubs_with_cache(tmp_path, [_article_xml(title="Done"), _article_xml(title="Todo")])
    existing = tmp_path / "existing.json"
    existing.write_text("[[]]", encoding="utf-8")
    pubs[0].content_json_filepath = existing

    converter = _make_transformer(pubs, db, tmp_path, max_workers=2)
    converter.transform_all()

    assert pubs[0].content_json_filepath == existing
    assert not converter._build_output_path(pubs[0]).exists()
    assert pubs[1].content_json_filepath is not None


def test_default_max_workers_min_one(monkeypatch):
    import os
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert ElsevierXmlTransformer(publication_list=[]).max_workers == 1
