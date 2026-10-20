import logging
import re
import pandas as pd
from pathlib import Path
from pydantic import ValidationError
from .publisher_map import publisher_map
from .doi_prefix_map import doi_prefix_map
from typing import Dict, List, Optional
from biomarkit.text_download.basemodels.publication import Publication

# Placeholder publisher for rows whose publisher is missing and can't be inferred. It matches no API client, so the
# router only tries the open-access routes for these papers.
UNKNOWN_PUBLISHER = "unknown"

_DOI_PREFIX = re.compile(r"^(10\.\d+)/")
_PREFIX_TO_CLIENT = {prefix: client for client, prefixes in doi_prefix_map.items() for prefix in prefixes}

# Funcs.
def load_scopus_csv(scopus_filepath: Path) -> pd.DataFrame:
    """
    Loads a raw csv produced from a SCOPUS query as a pandas dataframe and drops all unneeded columns.
    Parameters
    ----------
    scopus_filepath: Path - A Pathlib.Path object referencing the raw input csv produced from the SCOPUS query.

    Returns
    -------
    pd.DataFrame
    """
    columns_to_keep = ["Title", "Year", "DOI", "Publisher"]

    logging.debug("Attempting to load scopus CSV file.")
    df = pd.read_csv(scopus_filepath, header=0, sep=",")

    if "Abstract" in df.columns:
        columns_to_keep.append("Abstract")
    else:
        logging.warning("'Abstract' column not found in Scopus CSV. Publication.abstract will be None.")

    df = df[columns_to_keep]
    logging.debug("Scopus CSV file loaded.")

    return df

def remove_imperfect_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Removes rows a Publication can't be built from: rows missing a DOI, Title or Year. Strips whitespace from DOIs
    and drops duplicate DOIs (keeping the first). Rows missing only a Publisher or Abstract are kept — they can still
    be downloaded via the open-access routes or a publisher inferred from the DOI.

    Parameters
    ----------
    df: pd.DataFrame

    Returns
    -------
    pd.DataFrame
    """
    logging.debug("Attempting to remove imperfect rows.")
    required = ["DOI", "Title", "Year"]
    missing = df[required].isna()
    _df = df[~missing.any(axis=1)].copy()
    _df["DOI"] = _df["DOI"].str.strip()
    duplicates = _df["DOI"].duplicated()
    _df = _df[~duplicates]

    removed = {column: int(missing[column].sum()) for column in required if missing[column].any()}
    if duplicates.any():
        removed["duplicate DOI"] = int(duplicates.sum())
    logging.info(f"{len(df) - len(_df)} row(s) removed from the Scopus CSV: {removed or 'none'}.")
    return _df

def infer_publisher_from_doi(doi: str) -> Optional[str]:
    """
    Guesses the API client for a DOI from its prefix (e.g. 10.1016 -> "elsevier") using doi_prefix_map.

    Parameters
    ----------
    doi: str

    Returns
    -------
    str or None - The client key, or None if the prefix is not in doi_prefix_map.
    """
    match = _DOI_PREFIX.match(doi.strip()) if isinstance(doi, str) else None
    return _PREFIX_TO_CLIENT.get(match.group(1)) if match else None

def synchronise_publishers(df: pd.DataFrame,
                           mapper: Dict[str, List[str]] = publisher_map,
                           column: str = "Publisher",
                           infer_from_doi: bool = True) -> pd.DataFrame:
    """
    Uses a known dictionary to attempt to standardise publisher names in the scopus query. The mapper dictionary can be
    added to over time to enable more accurate standardisation. Creates a new column named "PublisherGroup". That will
    be used to assign DOI's to API clients for download.

    When infer_from_doi is True, rows whose publisher is missing or doesn't map to an API client get a publisher
    inferred from their DOI prefix (see infer_publisher_from_doi). A publisher that maps to a client is never
    overridden. Rows still without a publisher get UNKNOWN_PUBLISHER.

    Parameters
    ----------
    df: pd.DataFrame
    mapper: Dict[str, List[str]]
    column: str
    infer_from_doi: bool

    Returns
    -------
    pd.DataFrame
    """
    from biomarkit.text_download.apis.map import api_clients

    df = df.copy()
    logging.debug("Attempting to synchronise publishers.")
    reverse_map = {value: key for key, values in mapper.items() for value in values}
    df["PublisherGroup"] = df[column].map(reverse_map).fillna(df[column])

    if infer_from_doi:
        unrouted = ~df["PublisherGroup"].isin(api_clients)
        inferred = df.loc[unrouted, "DOI"].map(infer_publisher_from_doi).dropna()
        if not inferred.empty:
            had_none = int(df.loc[inferred.index, column].isna().sum())
            df.loc[inferred.index, "PublisherGroup"] = inferred
            logging.info(f"Inferred publisher from DOI prefix for {len(inferred)} row(s) "
                         f"({had_none} had no publisher, {len(inferred) - had_none} were unrecognised).")

    df["PublisherGroup"] = df["PublisherGroup"].fillna(UNKNOWN_PUBLISHER)
    logging.debug("Synchronised publishers.")

    return df

def build_publication_objects(df: pd.DataFrame) -> List[Publication]:
    """
    Creates a Publication object for each row in a pandas dataframe. Returns a list of publication objects. Validation
    is handled by the Publication class; a row that fails validation (e.g. a DOI the Publication DOI check rejects)
    is skipped with a warning rather than aborting the whole build.

    Parameters
    ----------
    df: pd.DataFrame - Filtered scopus query in pandas dataframe format.

    Returns
    -------
    List[Publication]
    """

    has_abstract = "Abstract" in df.columns

    logging.debug("Attempting to build a list of publication objects.")
    publications = []
    for row in df.itertuples(index=False):
        abstract = row.Abstract if has_abstract and pd.notna(row.Abstract) else None
        try:
            publications.append(Publication(
                doi=row.DOI,
                title=row.Title,
                publisher=row.PublisherGroup,
                year=row.Year,
                abstract=abstract,
            ))
        except ValidationError as e:
            logging.warning(f"Skipping Scopus row for DOI {row.DOI!r}: {e.errors()[0]['msg']}")
    return publications
