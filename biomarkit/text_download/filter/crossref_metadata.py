"""
Builds publication metadata for a plain list of DOIs from the Crossref REST API (https://api.crossref.org), as an
alternative to a Scopus export. The frame returned has the same columns load_scopus_csv() produces, so it goes through
the same filtering and publisher synchronisation.
"""

import logging
import re
from pathlib import Path

import pandas as pd
import requests

from biomarkit.config import USER_EMAIL

CROSSREF_WORKS_URL = "https://api.crossref.org/works"
_DOI_PREFIX_RE = re.compile(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def read_dois(dois: "str | Path | list[str]") -> list[str]:
    """
    Normalises DOI input. A list is used as-is; a str or Path is read as a text file with one DOI per line (blank
    lines and lines starting with '#' are skipped). URL and 'doi:' prefixes are stripped and duplicates are dropped
    case-insensitively, keeping the first spelling.
    """
    if isinstance(dois, (str, Path)):
        lines = Path(dois).read_text(encoding="utf-8-sig").splitlines()
        dois = [line for line in lines if not line.strip().startswith("#")]

    seen, result = set(), []
    for doi in dois:
        doi = _DOI_PREFIX_RE.sub("", doi.strip())
        if doi and doi.lower() not in seen:
            seen.add(doi.lower())
            result.append(doi)
    return result


def _clean_abstract(abstract: str | None) -> str | None:
    """Strips Crossref's JATS markup (<jats:p>, <jats:title>, ...) from an abstract."""
    if not abstract:
        return None
    return " ".join(_TAG_RE.sub(" ", abstract).split()) or None


def _query_batch(batch: list[str], timeout: int) -> list[dict] | None:
    """Fetches the Crossref records for one batch of DOIs, retrying once. Returns None if both attempts fail."""
    params = {
        "filter": ",".join(f"doi:{doi}" for doi in batch),
        "rows": 2 * len(batch),
        "select": "DOI,title,issued,publisher,abstract",
        "mailto": USER_EMAIL,
    }
    for attempt in range(2):
        try:
            resp = requests.get(CROSSREF_WORKS_URL, params=params, timeout=timeout,
                                headers={"User-Agent": "biomarkit/1.0"})
            resp.raise_for_status()
            return resp.json()["message"]["items"]

        except (requests.exceptions.RequestException, ValueError, KeyError) as e:
            logging.warning(f"Crossref lookup failed for {len(batch)} DOIs (attempt {attempt + 1}) - {e}")
    return None


def fetch_crossref_metadata(dois: list[str], batch_size: int = 50, timeout: int = 60) -> pd.DataFrame:
    """
    Fetches Title, Year, Publisher and Abstract for each DOI from Crossref, batch_size DOIs per request. Requests run
    sequentially (the Crossref public pool allows one concurrent request). DOIs Crossref can't resolve, or whose
    record has no title or year, are logged and left out.

    Parameters
    ----------
    dois: list[str] - DOIs as returned by read_dois().
    batch_size: int - DOIs per Crossref request.
    timeout: int - Request timeout in seconds.

    Returns
    -------
    pd.DataFrame - Columns Title, Year, DOI, Publisher, Abstract, in input order. DOIs keep their input spelling.
    """
    records = {}
    for i in range(0, len(dois), batch_size):
        for item in _query_batch(dois[i:i + batch_size], timeout) or []:
            records[item.get("DOI", "").lower()] = item

    rows, unresolved = [], []
    for doi in dois:
        item = records.get(doi.lower())
        title = (item or {}).get("title") or [None]
        year = ((item or {}).get("issued") or {}).get("date-parts", [[None]])[0][0]
        if not item or not title[0] or not year:
            unresolved.append(doi)
            continue
        rows.append({"Title": title[0], "Year": year, "DOI": doi, "Publisher": item.get("publisher"),
                     "Abstract": _clean_abstract(item.get("abstract"))})

    logging.info(f"Crossref returned metadata for {len(rows)}/{len(dois)} DOIs.")
    if unresolved:
        logging.warning(f"{len(unresolved)} DOI(s) had no Crossref title/year and were dropped: {', '.join(unresolved)}")

    return pd.DataFrame(rows, columns=["Title", "Year", "DOI", "Publisher", "Abstract"])
