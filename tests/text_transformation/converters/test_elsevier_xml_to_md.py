import json
import xml.etree.ElementTree as ET
from pathlib import Path
from text_download.basemodels.publication import Publication
from text_transformation.converters.elsevier_xml_to_md import (
    ElsevierXmlTransformer,
    clean_text,
    get_element_text,
    extract_title,
    extract_authors,
    extract_abstract,
    extract_keywords,
    parse_figure,
    parse_table,
    parse_body_sections,
    extract_references,
    _parse_mathml,
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
# extract_authors
# ---------------------------------------------------------------------------

def test_extract_authors_single():
    root = _root(_article_xml(author_given="Jane", author_surname="Smith"))
    authors = extract_authors(root)
    assert len(authors) == 1
    assert "Smith" in authors[0]
    assert "Jane" in authors[0]


def test_extract_authors_no_authors_returns_empty():
    root = _root(_MINIMAL_XML)
    assert extract_authors(root) == []


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
# extract_keywords
# ---------------------------------------------------------------------------

def test_extract_keywords():
    root = _root(_article_xml(keywords=["biomarker", "machine learning"]))
    kws = extract_keywords(root)
    assert "biomarker" in kws
    assert "machine learning" in kws


def test_extract_keywords_none_returns_empty():
    root = _root(_MINIMAL_XML)
    assert extract_keywords(root) == []


# ---------------------------------------------------------------------------
# parse_figure
# ---------------------------------------------------------------------------

def test_parse_figure_label_and_caption():
    xml = (
        f'<ce:figure xmlns:ce="{CE}">'
        f'<ce:label xmlns:ce="{CE}">Fig. 1</ce:label>'
        f'<ce:caption xmlns:ce="{CE}">'
        f'<ce:simple-para xmlns:ce="{CE}">A caption.</ce:simple-para>'
        f'</ce:caption>'
        f'</ce:figure>'
    )
    result = parse_figure(ET.fromstring(xml))
    assert "Fig. 1" in result
    assert "A caption." in result


def test_parse_figure_label_only():
    xml = f'<ce:figure xmlns:ce="{CE}"><ce:label xmlns:ce="{CE}">Fig. 2</ce:label></ce:figure>'
    assert parse_figure(ET.fromstring(xml)) == "[Fig. 2]"


def test_parse_figure_empty_returns_empty():
    xml = f'<ce:figure xmlns:ce="{CE}"/>'
    assert parse_figure(ET.fromstring(xml)) == ""


# ---------------------------------------------------------------------------
# parse_table
# ---------------------------------------------------------------------------

def test_parse_table_label_and_caption():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<ce:label xmlns:ce="{CE}">Table 1</ce:label>'
        f'<ce:caption xmlns:ce="{CE}">'
        f'<ce:simple-para xmlns:ce="{CE}">Summary of results.</ce:simple-para>'
        f'</ce:caption>'
        f'</ce:table>'
    )
    result = parse_table(ET.fromstring(xml))
    assert "Table 1" in result
    assert "Summary of results." in result


def test_parse_table_with_rows():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<ce:label xmlns:ce="{CE}">Table 2</ce:label>'
        f'<tgroup>'
        f'<thead><row><entry>Col A</entry><entry>Col B</entry></row></thead>'
        f'<tbody>'
        f'<row><entry>1</entry><entry>2</entry></row>'
        f'<row><entry>3</entry><entry>4</entry></row>'
        f'</tbody>'
        f'</tgroup>'
        f'</ce:table>'
    )
    result = parse_table(ET.fromstring(xml))
    assert "Col A" in result
    assert "Col B" in result
    assert "| 1 | 2 |" in result


def test_parse_table_pipe_escaped_in_cells():
    xml = (
        f'<ce:table xmlns:ce="{CE}">'
        f'<tgroup>'
        f'<thead><row><entry>H1</entry></row></thead>'
        f'<tbody><row><entry>a|b</entry></row></tbody>'
        f'</tgroup>'
        f'</ce:table>'
    )
    result = parse_table(ET.fromstring(xml))
    assert r"a\|b" in result


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
# parse_body_sections
# ---------------------------------------------------------------------------

def test_parse_body_sections_extracts_heading_and_para():
    xml = (
        f'<root xmlns:ce="{CE}">'
        f'<ce:sections>'
        f'<ce:section>'
        f'<ce:section-title>Introduction</ce:section-title>'
        f'<ce:para>First paragraph.</ce:para>'
        f'</ce:section>'
        f'</ce:sections>'
        f'</root>'
    )
    result = parse_body_sections(ET.fromstring(xml))
    assert "Introduction" in result
    assert "First paragraph." in result


def test_parse_body_sections_empty_when_no_sections():
    xml = f'<root xmlns:ce="{CE}"/>'
    assert parse_body_sections(ET.fromstring(xml)) == ""


def test_parse_body_sections_nested_subsection():
    xml = (
        f'<root xmlns:ce="{CE}">'
        f'<ce:sections>'
        f'<ce:section>'
        f'<ce:section-title>Methods</ce:section-title>'
        f'<ce:section>'
        f'<ce:section-title>Data collection</ce:section-title>'
        f'<ce:para>We collected data.</ce:para>'
        f'</ce:section>'
        f'</ce:section>'
        f'</ce:sections>'
        f'</root>'
    )
    result = parse_body_sections(ET.fromstring(xml))
    assert "Methods" in result
    assert "Data collection" in result
    assert "We collected data." in result


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
