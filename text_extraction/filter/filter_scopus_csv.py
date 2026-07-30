import logging
import pandas as pd
from pathlib import Path
from .publisher_map import publisher_map
from typing import Dict, List
from text_extraction.basemodels.publication import Publication

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

    logging.info("Attempting to load scopus CSV file.")
    df = pd.read_csv(scopus_filepath, header=0, sep=",")

    if "Abstract" in df.columns:
        columns_to_keep.append("Abstract")
    else:
        logging.warning("'Abstract' column not found in Scopus CSV. Publication.abstract will be None.")

    df = df[columns_to_keep]
    logging.info("Scopus CSV file loaded.")

    return df

def remove_imperfect_rows(df: pd.DataFrame) -> pd.DataFrame:
    """
    Carries out a number of filtering steps to remove imperfect rows within the dataframe
    Parameters
    ----------
    df: pd.DataFrame

    Returns
    -------
    pd.DataFrame
    """
    logging.info("Attempting to remove imperfect rows.")
    _df = df.dropna()
    logging.info(f"{len(df) - len(_df)} Rows removed due to imperfections.")
    return _df

def synchronise_publishers(df: pd.DataFrame,
                           mapper: Dict[str, List[str]] = publisher_map,
                           column: str = "Publisher") -> pd.DataFrame:
    """
    Uses a known dictionary to attempt to standardise publisher names in the scopus query. The mapper dictionary can be
    added to over time to enable more accurate standardisation. Creates a new column named "Publisher Group". That will
    be used to assign DOI's to API clients for download.

    Parameters
    ----------
    df: pd.DataFrame
    mapper: Dict[str, List[str]]
    column: str

    Returns
    -------
    pd.DataFrame
    """
    df = df.copy()
    logging.info("Attempting to synchronise publishers.")
    reverse_map = {value: key for key, values in mapper.items() for value in values}
    df["PublisherGroup"] = df[column].map(reverse_map).fillna(df[column])
    logging.info("Synchronised publishers.")

    return df

def build_publication_objects(df: pd.DataFrame) -> List[Publication]:
    """
    Creates a Publication object for each row in a pandas dataframe. Returns a list of publication objects. Validation
    is handled by the Publication class and will raise Pydantic validation errors accordingly.

    Parameters
    ----------
    df: pd.DataFrame - Filtered scopus query in pandas dataframe format.

    Returns
    -------
    List[Publication]
    """

    has_abstract = "Abstract" in df.columns

    logging.info("Attempting to build a list of publication objects.")
    return [
        Publication(
            doi=row.DOI,
            title=row.Title,
            publisher=row.PublisherGroup,
            year=row.Year,
            abstract=row.Abstract if has_abstract else None,
        )
        for row in df.itertuples(index=False)
    ]
