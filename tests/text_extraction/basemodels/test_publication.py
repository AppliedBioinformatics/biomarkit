import pytest
from pydantic_core import ValidationError
from text_extraction.basemodels.publication import Publication, DocumentType
from config import TMP_DIR

def test_publication_success_no_file():
    # Create a new publication without a cached file.
    pub = Publication(
        doi="10.1038/s41586-020-2649-2",
        title="A groundbreaking study",
        publisher="Nature",
        year=2020,
        document_type=DocumentType.PDF
    )

    # Test everything is stored correctly.
    assert pub.doi == "10.1038/s41586-020-2649-2"
    assert pub.title == "A groundbreaking study"
    assert pub.publisher == "Nature"
    assert pub.year == 2020
    assert pub.document_type == DocumentType.PDF
    assert pub.publication_filepath is None

    # Asserts for properties.
    assert pub.is_cached == False

def test_publication_success_with_file(tmp_path):
    # Set up a file.
    file_path = TMP_DIR / "tests_tmp" / "test.pdf"
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text("test_content")

    # Set up initial Publication.
    pub = Publication(
        doi="10.1038/s41586-020-2649-2",
        title="A groundbreaking study",
        publisher="Nature",
        year=2020,
        document_type=DocumentType.PDF
    )

    # Update filepath.
    pub.publication_filepath = file_path

    # Asserts.
    assert pub.publication_filepath == file_path
    assert pub.is_cached == True

    # Cleanup.
    if file_path.exists():
        file_path.unlink()

def test_publication_fail_future_date():
    # Future date.
    with pytest.raises(ValueError):
        Publication(
            doi="10.1038/s41586-020-2649-2",
            title="A groundbreaking study",
            publisher="Nature",
            year=3000,
            document_type=DocumentType.PDF
        )

    # Date too old.
    with pytest.raises(ValueError):
        Publication(
            doi="10.1038/s41586-020-2649-2",
            title="A groundbreaking study",
            publisher="Nature",
            year=1899,
            document_type=DocumentType.PDF
        )

def test_publication_fail_wrong_document_type():
    with pytest.raises(ValueError):
        Publication(
            doi="10.1038/s41586-020-2649-2",
            title="A groundbreaking study",
            publisher="Nature",
            year=3000,
            document_type="PDF"
        )

def test_publication_fail_null_values():
    # No DOI.
    with pytest.raises(ValueError):
        Publication(
            doi=None,
            title="A groundbreaking study",
            publisher="Nature",
            year=3000,
            document_type=DocumentType.PDF
        )

    # No Title.
    with pytest.raises(ValueError):
        Publication(
            doi="10.1038/s41586-020-2649-2",
            title=None,
            publisher="Nature",
            year=3000,
            document_type=DocumentType.PDF
        )

def test_publication_validate_doi_success():

    # Test different valid DOI's.
    valid_dois = ["10.1000/xyz123",
                  "10.12345/abc.def",
                  "10.54321/HELLO-WORLD",
                  "10.10000/12345(abc):6789"]

    for doi in valid_dois:
        pub = Publication(
            doi=doi,
            title="A groundbreaking study",
            publisher="Nature",
            year=2020,
            document_type=DocumentType.PDF
        )
        assert pub.doi == doi

def test_publication_validate_doi_fail():

    # Test different invalid DOI's.
    invalid_dois = ["11.1000/xyz123",
                    "10.100/xyz123",
                    "10.100000000/abc",
                    "10.1000",
                    "abcd/10.1000/xyz",
                    "10.1000 xyz123",
                    "10.1000/"]

    with pytest.raises(ValidationError):
        for doi in invalid_dois:
            Publication(
                doi=doi,
                title="A groundbreaking study",
                publisher="Nature",
                year=2020,
                document_type=DocumentType.PDF
            )

def test_publication_is_cached_property():
    pub = Publication(doi="10.1037/arc0000014", title="Test", year=2020, publisher="Nature")
    assert pub.is_cached is False
    pub.publication_filepath = "/some/location"
    assert pub.is_cached is True

def test_publication_is_chunked_property_none():
    pub = Publication(doi="10.1037/arc0000014", title="Test", year=2020, publisher="Nature")
    assert pub.is_chunked is False

def test_publication_is_chunked_property_empty_list():
    pub = Publication(doi="10.1037/arc0000014", title="Test", year=2020, publisher="Nature")
    pub.chunks = []
    assert pub.is_chunked is False

def test_publication_is_chunked_property_with_items():
    pub = Publication(doi="10.1037/arc0000014", title="Test", year=2020, publisher="Nature")
    pub.chunks = ["chunk_1"]
    assert pub.is_chunked is True
