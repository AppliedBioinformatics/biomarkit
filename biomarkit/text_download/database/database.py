import sqlite3
from pathlib import Path
from typing import Union

DB_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT UNIQUE NOT NULL,
    downloaded_from TEXT NOT NULL,
    publication_filepath TEXT NOT NULL,
    content_json_filepath TEXT,
    final_md_filepath TEXT)
    """

def create_database(db_path: Path, del_existing: bool = False) -> None:
    """
    Creates a database.

    Parameters
    ----------
    db_path: Path - Pathlib.Path object for the location of the database file (sqlite3).
    del_existing: bool - If true, will overwrite the existing database at db_path if it already exists.

    Returns
    -------
    None
    """

    if del_existing and db_path.exists():
        db_path.unlink()

    # Build.
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(DB_SCHEMA)
        conn.commit()


def insert_row(doi: str, downloaded_from: str, publication_filepath: str, db_path: Union[str, Path]) -> None:
    """
    Inserts a row into the 'cache' table of the SQLite database.

    Parameters
    ----------
    doi : str - The DOI of the item (must be unique).
    downloaded_from : Optional[str] - Source from which the item was downloaded.
    publication_filepath : Optional[str] - Filepath where the item is stored.
    db_path: Union[Path, str] - Pathlib.Path object or str for the location of the database file (sqlite3).
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO cache (doi, downloaded_from, publication_filepath) VALUES (?, ?, ?)",
            (doi, downloaded_from, publication_filepath)
        )
        conn.commit()

    except sqlite3.IntegrityError:
        print(f"Row with DOI '{doi}' already exists.")

    finally:
        conn.close()

def update_content_json_filepath(doi: str, content_json_filepath: str, db_path: Union[str, Path]) -> None:
    """
    Updates the content_json_filepath column for an existing cache row identified by DOI.

    Parameters
    ----------
    doi : str - The DOI of the publication to update.
    content_json_filepath : str - Path to the content_list_v2.json file produced by the converter.
    db_path : Union[str, Path] - Path to the SQLite database file.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE cache SET content_json_filepath = ? WHERE doi = ?",
            (content_json_filepath, doi)
        )
        conn.commit()


def update_final_md_filepath(doi: str, final_md_filepath: str, db_path: Union[str, Path]) -> None:
    """
    Updates the final_md_filepath column for an existing cache row identified by DOI.

    Parameters
    ----------
    doi : str - The DOI of the publication to update.
    final_md_filepath : str - Path to the final cleaned markdown file.
    db_path : Union[str, Path] - Path to the SQLite database file.
    """
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "UPDATE cache SET final_md_filepath = ? WHERE doi = ?",
            (final_md_filepath, doi)
        )
        conn.commit()


def get_row_for_doi(doi: str, db_path: Path) -> dict or None:
    """
    Searches the cache for a DOI. Returns the row if found, None otherwise. Row is returned in the following format:
    {"doi": <value>, "downloaded_from": <value>, "publication_filepath": <value>, "content_json_filepath": <value>, "final_md_filepath": <value>}

    Parameters
    ----------
    db_path: Optional[str] - Pathlib.Path object for the location of the database file (sqlite3).
    doi: str - The DOI of a publication.

    Returns
    -------
    dict or None
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # allows fetching rows as dict-like objects
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM cache WHERE doi = ?", (doi,))
    row = cursor.fetchone()
    conn.close()

    if row is not None:
        return dict(row)

    return None