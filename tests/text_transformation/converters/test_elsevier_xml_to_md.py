from pathlib import Path
from text_extraction.basemodels.publication import Publication
from text_transformation.converters.elsevier_xml_to_md import ElsevierXmlConverter

_MINIMAL_XML = """<?xml version="1.0"?>
<full-text-retrieval-response xmlns="http://www.elsevier.com/xml/svapi/article/dtd">
  <coredata><dc:title xmlns:dc="http://purl.org/dc/elements/1.1/">Test Title</dc:title></coredata>
</full-text-retrieval-response>"""


def test_convert_creates_stem_subdirectory(tmp_path):
    """convert() creates output_dir/<stem>/ and writes output_dir/<stem>/<stem>.md."""
    xml_path = tmp_path / "elsevier_1234567890.xml"
    xml_path.write_text(_MINIMAL_XML, encoding="utf-8")

    pub = Publication(
        doi="10.1016/test",
        title="Test",
        publisher="Elsevier",
        year=2020,
        publication_filepath=xml_path,
    )

    converter = ElsevierXmlConverter(publication_list=[pub])
    converter.output_dir = tmp_path

    result = converter.convert(pub)

    stem = xml_path.stem
    expected = tmp_path / stem / f"{stem}.md"
    assert result == expected
    assert expected.exists()
    assert expected.parent.is_dir()