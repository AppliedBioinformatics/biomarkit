import logging
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from pydantic import FilePath
from plotly import graph_objects as go, io as pio
from collections import defaultdict
from tqdm import tqdm
from text_download.basemodels.publication import Publication
from text_download.database.database import create_database
from config import LOG_DIR, DOWNLOAD_DIR, REPORT_DIR, DB_CACHE_FILE_NAME, SCOPUS_INPUT_CSV_NAME


class _TqdmLoggingHandler(logging.Handler):
    """Routes log records through tqdm.write so active bars aren't interrupted."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record))
        except Exception:
            self.handleError(record)


def _secrets_path() -> Path:
    return Path(__file__).resolve().parents[2] / "secrets.env"


def create_corpus(name: str) -> Path:
    """
    Creates the folder structure for a new corpus at corpora/<name>.

    Builds the empty corpus subfolders (manuscripts, intermediates, results, reports, logs).
    Safe to call on an existing corpus — existing contents are left untouched.

    Parameters
    ----------
    name : str
        Folder name for the new corpus (no path separators).

    Returns
    -------
    Path
        Path to the corpus folder.
    """
    from config import (
        CORPORA_DIR, DOWNLOAD_DIR, JSON_STRUCT_DIR, FINAL_MARKDOWN_DIR, REPORT_DIR, LOG_DIR, SCOPUS_INPUT_CSV_NAME
    )

    name = name.strip()
    if not name or set('\\/:*?"<>|') & set(name):
        raise ValueError(
            f"Invalid corpus name: {name!r}. Use a plain folder name without path separators."
        )

    corpus_dir = CORPORA_DIR / name
    if corpus_dir.exists():
        logging.warning(f"Corpus '{name}' already exists at {corpus_dir} — leaving existing contents untouched.")

    for subdir_name in (
        DOWNLOAD_DIR.name, JSON_STRUCT_DIR.name, FINAL_MARKDOWN_DIR.name, REPORT_DIR.name, LOG_DIR.name,
    ):
        (corpus_dir / subdir_name).mkdir(parents=True, exist_ok=True)

    logging.info(
        f"Corpus '{name}' ready at {corpus_dir}. Place your Scopus export there as "
        f"'{SCOPUS_INPUT_CSV_NAME.name}' and set CORPUS_NAME = \"{name}\" in secrets.env to use it."
    )
    return corpus_dir


def build_new_corpus(name: str, scopus_file: "str | Path", set_active: bool = True) -> Path:
    """
    Creates the folder structure for a new corpus and copies the Scopus CSV into it.

    Parameters
    ----------
    name : str
        Folder name for the new corpus (no path separators).
    scopus_file : str | Path
        Path to the Scopus export CSV to seed the corpus with.
    set_active : bool, default True
        When True, writes CORPUS_NAME=<name> into secrets.env so subsequent
        pipeline calls target this corpus without any manual edits.

    Returns
    -------
    Path
        Path to the newly created corpus folder.
    """
    import re
    import shutil

    scopus_src = Path(scopus_file)
    if not scopus_src.exists():
        raise FileNotFoundError(f"Scopus CSV not found: {scopus_src}")

    corpus_dir = create_corpus(name)

    dest = corpus_dir / "scopus.csv"
    if not dest.exists():
        shutil.copy2(scopus_src, dest)
        logging.info(f"Copied Scopus CSV to {dest}.")
    else:
        logging.warning(f"Scopus CSV already exists at {dest} — leaving it untouched.")

    if set_active:
        secrets_path = _secrets_path()
        if secrets_path.exists():
            text = secrets_path.read_text(encoding="utf-8")
            updated = re.sub(
                r"^(CORPUS_NAME\s*=).*",
                rf"\g<1>{name}",
                text,
                count=1,
                flags=re.MULTILINE,
            )
            secrets_path.write_text(updated, encoding="utf-8")
        else:
            secrets_path.write_text(f"CORPUS_NAME={name}\n", encoding="utf-8")
        logging.info(f"Set CORPUS_NAME={name} in {secrets_path}.")

    return corpus_dir


def setup_logging(level=logging.INFO):
    """
    This function should be called at the beginning of main() to set up logging configuration.
    Routes console output through tqdm.write so active progress bars aren't interrupted.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Remove any existing console (StreamHandler) handlers, keeping FileHandlers.
    root.handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]

    handler = _TqdmLoggingHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    root.addHandler(handler)

    # Silence third-party per-item info logs that clutter the console.
    logging.getLogger("wiley_tdm").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logging.debug("SETUP - Completed setting up logging.")
    if level == logging.DEBUG:
        logging.debug("Running programme in DEBUG mode.")

def setup_run():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    if not SCOPUS_INPUT_CSV_NAME.exists():
        raise FileNotFoundError(
            f"No Scopus CSV found for corpus at {SCOPUS_INPUT_CSV_NAME}. "
            f"Place your Scopus export there before running the pipeline."
        )

    if not DB_CACHE_FILE_NAME.exists():
        logging.info("SETUP - No cache file found. Making a new one.")
        create_database(db_path=DB_CACHE_FILE_NAME)

def clean_publications(folder: Path = DOWNLOAD_DIR, db_path: Path = DB_CACHE_FILE_NAME):
    """
    This function should be called at the beginning of main to make sure that no publications exists inside
    'publication_dir' that are not saved within the cache.
    """

    logging.info("SETUP - Cleaning publications.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Query DB.
    query = f"SELECT publication_filepath FROM cache WHERE publication_filepath IS NOT NULL"
    cursor.execute(query)


    # Store tracked paths in a set for faster lookup
    tracked_files = {Path(row[0]) for row in cursor.fetchall()}
    logging.debug(f"SETUP - Found {len(tracked_files)} publications stored in cache.")
    conn.close()

    # Delete file if not stored in cache.
    deleted_files = 0
    for file_path in folder.iterdir():
        if file_path.is_file():
            if file_path not in tracked_files:
                logging.warning(f"SETUP - File {file_path} is not stored in cache?")
                file_path.unlink()
                deleted_files += 1

    logging.info(f"SETUP - Cleanup complete. Deleted {deleted_files} uncached file(s).")

def build_plotly_report(figures: List[go.Figure], output_file: str, title: Optional[str] = "Data Report",
                        subtitle: Optional[str] = None,
                        html_sections: Optional[List[str]] = None) -> str:
    """
    Generate a standalone HTML report from a list of Plotly figures passed as an argument. Optional parameters "title"
    and "subtitle" are available to customise the HTML report.

    Parameters:
        figures (List[Figure]): List of Plotly figures (plotly.express or graph_objects).
        title (str): Title for the report.
        subtitle (str): Subtitle or description for the report.
        output_file (str): If specified, saves the HTML to this file.
        html_sections (List[str] | None): Optional list of raw HTML strings injected after the figures.

    Returns:
        str: The complete HTML string of the report.
    """

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_figures = ""
    for i, fig in enumerate(figures):
        fig.update_layout(height=600)

        # First figure includes JS via CDN, rest don't
        html_figures += f"""
            <div class="figure-container">
                {pio.to_html(fig, include_plotlyjs='cdn' if i == 0 else False, full_html=False)}
            </div>
            """

    html_raw = ""
    if html_sections:
        for block in html_sections:
            html_raw += f'<div class="figure-container">{block}</div>\n'

    html_template = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <title>{title}</title>
            <style>
                body {{
                    font-family: 'Segoe UI', sans-serif;
                    margin: 40px;
                    background-color: #fafafa;
                    color: #333;
                }}
                h1 {{
                    font-size: 2.5em;
                    margin-bottom: 0.2em;
                }}
                h2 {{
                    font-weight: normal;
                    color: #666;
                }}
                .timestamp {{
                    font-size: 0.9em;
                    color: #999;
                    margin-bottom: 30px;
                }}
                .figure-container {{
                    margin-bottom: 50px;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.05);
                    padding: 10px;
                    background-color: white;
                    border-radius: 8px;
                }}
            </style>
        </head>
        <body>
            <h1>{title}</h1>
            {"<h2>" + subtitle + "</h2>" if subtitle else ""}
            <div class="timestamp">Generated on {timestamp}</div>
            {html_figures}
            {html_raw}
        </body>
        </html>
        """

    # Save.
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html_template)

    print(f"Report saved to {output_file}")
    return html_template

_ANSI_GREEN = "\033[32m"
_ANSI_RED   = "\033[31m"
_ANSI_RESET = "\033[0m"


def progress_split_bar(success: int, failed: int, total: int, width: int = 20) -> str:
    """
    Returns an ANSI-coloured ASCII bar split across `width` characters:
      Green █  = successful so far
      Red   █  = failed so far
      Grey  ░  = not yet attempted
    Proportions are relative to `total` (all items, including pending).
    """
    if total == 0:
        return "░" * width
    green_cells = round(success / total * width)
    red_cells   = min(round(failed / total * width), width - green_cells)
    pending     = width - green_cells - red_cells
    return (
        f"{_ANSI_GREEN}{'█' * green_cells}{_ANSI_RESET}"
        f"{_ANSI_RED}{'█' * red_cells}{_ANSI_RESET}"
        f"{'░' * pending}"
    )


def truncate_labels(label: str) -> str:
    return label if len(label) <= 50 else label[:47] + "…"

def validate_pdf_file(filepath: FilePath, eof_scan_bytes: int = 2048) -> bool:
    """
    Fast PDF check that requires no external dependencies. Validates that the file has the following:
        - Exists and is non-empty
        - Starts with the PDF header "%PDF-"
        - Contains an EOF marker "%%EOF" within the last `eof_scan_bytes` bytes.

    Parameters
    ----------
    filepath : FilePath (Pydantic)
        Path to the PDF file.
    eof_scan_bytes : int, default 2048
        Number of bytes from the end of the file to scan for the EOF marker.

    bool
        True if the file appears to be a valid PDF by these heuristics, else False.
    """

    logging.debug(f"Validating PDF file {filepath}.")
    try:
        p = Path(filepath)
        if not p.exists():
            return False

        size = p.stat().st_size
        if size < 1:
            return False

        with p.open("rb") as f:
            header = f.read(5)
            if header != b"%PDF-":
                return False

            tail_start = max(0, size - eof_scan_bytes)
            f.seek(tail_start)
            tail = f.read()
            if b"%%EOF" not in tail:
                return False

        logging.debug(f"PDF file {p} passed PDF validation.")
        return True

    except Exception as e:
        logging.info(f"PDF file {filepath} did not pass PDF validation. Error: {e}.")

def validate_xml_file(filepath: FilePath) -> bool:
    """
    Fast XML check with no external dependencies.

    Validates that the file:
      - exists and is non-empty
      - appears to start with an XML tag ("<", allowing for BOM/whitespace)
      - is well-formed (parsable by Python's standard xml.etree.ElementTree)

    Parameters
    ----------
    filepath : FilePath (Pydantic)
        Path to the XML file.

    Returns
    -------
    bool
        True if the file appears to be a valid XML by these heuristics; False otherwise.
    """
    logging.debug(f"Validating XML file {filepath}.")
    try:
        p = Path(filepath)
        if not p.exists():
            return False

        size = p.stat().st_size
        if size < 1:
            return False

        # Quick header sanity: should begin with '<' after optional BOM/whitespace
        with p.open("rb") as f:
            start = f.read(128)  # small sniff

        # Strip common BOMs
        for bom in (b"\xef\xbb\xbf", b"\xfe\xff", b"\xff\xfe", b"\x00\x00\xfe\xff", b"\xff\xfe\x00\x00"):
            if start.startswith(bom):
                start = start[len(bom):]
                break

        if not start.lstrip().startswith(b"<"):
            return False

        # Well-formedness check
        try:
            ET.parse(str(p))
        except ET.ParseError:
            return False

        logging.debug(f"XML file {p} passed XML validation.")
        return True

    except Exception as e:
        logging.info(f"XML file {filepath} did not pass XML validation. Error: {e}.")
        return False

def validate_publications(publication_list: List[Publication])-> dict:
    """
    Wrapper function to loop through and validate each publication in publication_list.

    Parameters
    ----------
    publication_list: List[Publication]

    Returns
    -------
    None
    """

    # Validate each file in self.finished_publications against it's filetype. Some finished publications may have
    # None as they were successfully routed to an API, but a download was not successful
    stats = defaultdict(lambda: {"total": 0, "valid": 0, "invalid": 0, "missing_path": 0})

    for pub in publication_list:
        filetype = (pub.document_type or "").upper()  # normalize, safe if None

        if filetype in {"PDF", "XML", "HTML"}:
            if pub.publication_filepath is None:
                stats[filetype]["missing_path"] += 1
                continue

            stats[filetype]["total"] += 1

            if filetype == "PDF":
                ok = validate_pdf_file(filepath=pub.publication_filepath)
                if not ok:
                    logging.warning(
                        f"PDF file at {pub.publication_filepath} for {pub.doi} is invalid."
                    )
            else:  # XML
                ok = validate_xml_file(filepath=pub.publication_filepath)
                if not ok:
                    logging.warning(
                        f"XML file at {pub.publication_filepath} for {pub.doi} is invalid."
                    )

            if ok:
                stats[filetype]["valid"] += 1
            else:
                stats[filetype]["invalid"] += 1

    return stats