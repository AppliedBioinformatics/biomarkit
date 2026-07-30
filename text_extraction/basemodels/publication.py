from pydantic import BaseModel, FilePath, field_validator, ConfigDict
from typing import Optional, List, Any
from enum import Enum
from datetime import datetime
import re

class DocumentType(str, Enum):
    PDF = "PDF"
    XML = "XML"
    HTML = "HTML"

class Publication(BaseModel):
    """
    Standardised publication model that all Scopus results are converted into post-filtering.

    Attributes
    ----------
    doi: str - Digital Object Identifier (DOI) of the publication.
    title: str - Title of the publication.
    publisher :str - Publisher of the publication.
    year: str - Year the publication was published.
    abstract: Optional[str] - Abstract of the publication, sourced from the Scopus CSV export. None if not available.
    document_type : DocumentType - Type of the publication document, restricted to values defined by DocumentType().
    publication_filepath: Path to the document file (must exist if provided).
    raw_md_filepath: Path to the raw unprocessed markdown file (must exist if provided).
    final_md_filepath: Path to the final processed markdown file (must exist if provided).
    chunks: Optional list of Chunk objects produced by the chunking pipeline.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    doi: str
    title: str
    publisher: str
    year: int
    abstract: Optional[str] = None
    document_type: DocumentType = "PDF"
    publication_filepath: Optional[FilePath] = None
    raw_md_filepath: Optional[FilePath] = None
    final_md_filepath: Optional[FilePath] = None
    chunks: Optional[List[Any]] = None  # List[Chunk] — typed as Any to avoid circular import

    @property
    def is_chunked(self) -> bool:
        return self.chunks is not None and len(self.chunks) > 0

    @property
    def is_cached(self) -> bool:
        return self.publication_filepath is not None

    @property
    def is_converted(self) -> bool:
        return self.raw_md_filepath is not None

    @property
    def is_processed(self) -> bool:
        return self.final_md_filepath is not None

    # Custom validators.
    @field_validator('doi')
    def validate_doi(cls, v) -> str:
        """Custom Pydantic validator for DOI formatting"""
        doi_regex = re.compile(r"^10\.\d{4,9}/[-._;()/:A-Z0-9]+$", re.IGNORECASE)
        if not doi_regex.match(v):
            raise ValueError(f"Invalid DOI: {v}")
        return v

    @field_validator('year')
    def validate_year(cls, v: str) -> str:
        """Custom Pydantic validator for year formatting - ensures year is not negative or in future."""
        current_year = datetime.now().year
        if v < 1900 or v > current_year + 1:
            raise ValueError(f"Invalid publication year: {v}")
        return v