import json
from pathlib import Path
from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_transformation.converters.bioc2json import (
    BioCXmlTransformer,
    _format_reference,
    _table_html,
    parse_bioc_xml_to_blocks,
)
from biomarkit.standardisation.content_list.schema import Document
from biomarkit.standardisation.content_list.filters import remove_figures, remove_references, remove_tables


def _passage(ptype, section, text="", **infons):
    extra = "".join(f'<infon key="{k}">{v}</infon>' for k, v in infons.items())
    return (f'<passage><infon key="section_type">{section}</infon><infon key="type">{ptype}</infon>{extra}'
            f'<offset>0</offset><text>{text}</text></passage>')


_TABLE_XML = ('&lt;?xml version="1.0" encoding="UTF-8"?&gt;&lt;table&gt;&lt;thead&gt;&lt;tr&gt;&lt;td&gt;Gene&lt;/td&gt;'
              '&lt;td&gt;p &amp;lt; 0.05&lt;/td&gt;&lt;/tr&gt;&lt;/thead&gt;&lt;tbody&gt;&lt;tr&gt;&lt;td&gt;BRCA1&lt;/td&gt;'
              '&lt;td&gt;yes&lt;/td&gt;&lt;/tr&gt;&lt;/tbody&gt;&lt;/table&gt;')

_BIOC = (
    '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE collection SYSTEM "BioC.dtd">'
    '<collection><source>PMC</source><document><id>123</id>'
    + _passage("front", "TITLE", "A study of things")
    + _passage("abstract_title_1", "ABSTRACT", "Background")
    + _passage("abstract", "ABSTRACT", "We studied things.")
    + _passage("title_1", "INTRO", "Introduction")
    + _passage("paragraph", "INTRO", "The BWT sentinel $ is appended to X=GOOGOL$.")
    + _passage("title_2", "METHODS", "Sub methods")
    + _passage("paragraph", "METHODS", "  Spaced\n text.  ")
    + _passage("paragraph", "METHODS", "")
    + _passage("table_title_caption", "TABLE", "Table title", id="T1", file="T1.xml")
    + _passage("table_caption", "TABLE", "Table caption.", id="T1", file="T1.xml")
    + _passage("table", "TABLE", "Gene\tp", id="T1", file="T1.xml", xml=_TABLE_XML)
    + _passage("table_foot", "TABLE", "Footnote a.", id="T1", file="T1.xml")
    + _passage("fig_title_caption", "FIG", "Figure title", id="F1", file="f1.jpg")
    + _passage("fig_caption", "FIG", "Figure caption.", id="F1", file="f1.jpg")
    + _passage("title", "ABBR", "Abbreviations")
    + _passage("footnote", "ABBR", "BWT: Burrows-Wheeler transform")
    + _passage("title", "REF", "REFERENCES")
    + _passage("ref", "REF", "A paper title.", name_0="surname:Smith;given-names:John A",
               name_1="surname:Doe;given-names:Jane", source="Bioinformatics", year="2009",
               volume="25", fpage="1754", lpage="1760")
    + _passage("ref", "REF", "")
    + '</document></collection>'
)


def _write(tmp_path, xml=_BIOC) -> Path:
    path = tmp_path / "bioc_0000000001.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def _text(block):
    content = block["content"]
    spans = content.get("paragraph_content") or content.get("title_content")
    return spans[0]["content"]


def test_parse_bioc_block_order_and_levels(tmp_path):
    blocks = parse_bioc_xml_to_blocks(str(_write(tmp_path)))[0]
    summary = [(b["type"], b["content"].get("level"), _text(b) if b["type"] in ("title", "paragraph") else None)
               for b in blocks]

    assert summary == [
        ("title", 1, "A study of things"),
        ("title", 2, "Abstract"),
        ("title", 3, "Background"),
        ("paragraph", None, "We studied things."),
        ("title", 2, "Introduction"),
        ("paragraph", None, "The BWT sentinel $ is appended to X=GOOGOL$."),
        ("title", 3, "Sub methods"),
        ("paragraph", None, "Spaced text."),
        ("table", None, None),
        ("image", None, None),
        ("title", 2, "Abbreviations"),
        ("paragraph", None, "BWT: Burrows-Wheeler transform"),
        ("title", 2, "References"),
        ("paragraph", None, "Smith JA, Doe J. A paper title. Bioinformatics 2009;25:1754-1760"),
    ]


def test_parse_bioc_dollar_is_plain_text(tmp_path):
    blocks = parse_bioc_xml_to_blocks(str(_write(tmp_path)))[0]
    spans = [s for b in blocks if b["type"] == "paragraph" for s in b["content"]["paragraph_content"]]
    assert all(s["type"] == "text" for s in spans)


def test_parse_bioc_groups_table_parts(tmp_path):
    table = next(b for b in parse_bioc_xml_to_blocks(str(_write(tmp_path)))[0] if b["type"] == "table")
    assert table["content"]["table_caption"][0]["content"] == "Table title Table caption."
    assert table["content"]["table_footnote"][0]["content"] == "Footnote a."
    assert table["content"]["html"] == ("<table><tr><th>Gene</th><th>p &lt; 0.05</th></tr>"
                                        "<tr><td>BRCA1</td><td>yes</td></tr></table>")


def test_parse_bioc_groups_figure_parts(tmp_path):
    image = next(b for b in parse_bioc_xml_to_blocks(str(_write(tmp_path)))[0] if b["type"] == "image")
    assert image["content"]["image_caption"][0]["content"] == "Figure title Figure caption."
    assert image["content"]["image_source"] == {"path": ""}


def test_parse_bioc_output_is_tagged_for_filters(tmp_path):
    out = tmp_path / "out.json"
    out.write_text(json.dumps(parse_bioc_xml_to_blocks(str(_write(tmp_path)))), encoding="utf-8")
    blocks = Document.from_file(out).blocks()

    blocks = remove_references(remove_figures(remove_tables(blocks)))
    texts = [b.content.paragraph_content[0].content for b in blocks if b.type == "paragraph"]

    assert "<table_removed>" in texts
    assert "<figure_removed>" in texts
    assert not any("Smith JA" in t for t in texts)


def test_table_html_bad_xml_returns_none():
    assert _table_html("<table><tr>") is None


def test_format_reference_partial_infons():
    assert _format_reference({"source": "Nature", "year": "2001"}, "") == "Nature 2001"
    assert _format_reference({"name_0": "collab:ENCODE Consortium"}, "Title") == "collab:ENCODE Consortium. Title"


def test_bioc_transformer_writes_content_list(tmp_path, active_corpus):
    pub = Publication(doi="10.1234/test", title="t", publisher="opensource", year=2020, document_type="XML",
                      publication_filepath=_write(tmp_path))
    transformer = BioCXmlTransformer(publication_list=[pub], max_workers=1)
    transformer.transform_all()

    assert pub.content_json_filepath.name == "bioc_0000000001_content_list_v2.json"
    pages = json.loads(pub.content_json_filepath.read_text(encoding="utf-8"))
    assert pages[0][0]["content"]["title_content"][0]["content"] == "A study of things"
