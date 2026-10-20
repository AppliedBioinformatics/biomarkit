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
from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_download.database.database import create_database
from biomarkit.config import get_corpus


class _TqdmLoggingHandler(logging.Handler):
    """Routes log records through tqdm.write so active bars aren't interrupted."""
    def emit(self, record: logging.LogRecord) -> None:
        try:
            tqdm.write(self.format(record))
        except Exception:
            self.handleError(record)


def resolve_corpus_path(corpus: "str | Path") -> Path:
    """
    Resolves a corpus reference to a folder path.

    A bare name (e.g. "my_corpus") resolves to CORPORA_DIR/<name>. An absolute path, or any value containing a path
    separator, is treated as a folder path.
    """
    from biomarkit.config import CORPORA_DIR

    if isinstance(corpus, Path) or Path(corpus).is_absolute() or "/" in corpus or "\\" in corpus:
        return Path(corpus).resolve()

    name = corpus.strip()
    if not name or set('\\/:*?"<>|') & set(name):
        raise ValueError(
            f"Invalid corpus name: {name!r}. Use a plain folder name or a path to a corpus folder."
        )
    return (CORPORA_DIR / name).resolve()


def build_corpus(corpus_dir: Path, scopus_file: "str | Path") -> Path:
    """
    Creates the folder structure for a corpus at corpus_dir and copies the Scopus CSV into it.

    Safe to call on an existing corpus — existing contents (including an existing scopus.csv) are left untouched.

    Parameters
    ----------
    corpus_dir : Path
        Folder to build the corpus in.
    scopus_file : str | Path
        Path to the Scopus export CSV to seed the corpus with.

    Returns
    -------
    Path
        Path to the corpus folder.
    """
    import shutil
    from biomarkit.config import CorpusPaths

    scopus_src = Path(scopus_file)
    if not scopus_src.exists():
        raise FileNotFoundError(f"Scopus CSV not found: {scopus_src}")

    paths = CorpusPaths(corpus_dir)
    for subdir in (paths.download_dir, paths.json_dir, paths.final_md_dir, paths.report_dir, paths.log_dir):
        subdir.mkdir(parents=True, exist_ok=True)

    if not paths.scopus_csv.exists():
        shutil.copy2(scopus_src, paths.scopus_csv)
        logging.info(f"Copied Scopus CSV to {paths.scopus_csv}.")
    else:
        logging.warning(f"Scopus CSV already exists at {paths.scopus_csv} — leaving it untouched.")

    logging.info(f"Corpus ready at {corpus_dir}.")
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
    corpus = get_corpus()
    corpus.log_dir.mkdir(parents=True, exist_ok=True)
    corpus.report_dir.mkdir(parents=True, exist_ok=True)
    corpus.download_dir.mkdir(parents=True, exist_ok=True)

    if not corpus.scopus_csv.exists():
        raise FileNotFoundError(
            f"No Scopus CSV found for corpus at {corpus.scopus_csv}. "
            f"Place your Scopus export there before running the pipeline."
        )

    if not corpus.db.exists():
        logging.info("SETUP - No cache file found. Making a new one.")
        create_database(db_path=corpus.db)

def clean_publications(folder: Optional[Path] = None, db_path: Optional[Path] = None):
    """
    This function should be called at the beginning of main to make sure that no publications exists inside
    'publication_dir' that are not saved within the cache. Defaults to the active corpus.
    """
    folder = folder or get_corpus().download_dir
    db_path = db_path or get_corpus().db

    logging.info("SETUP - Cleaning publications.")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Query DB.
    query = f"SELECT publication_filepath FROM cache WHERE publication_filepath IS NOT NULL"
    cursor.execute(query)


    # Store tracked paths in a set for faster lookup
    tracked_files = {(Path(db_path).parent / row[0]).resolve() for row in cursor.fetchall()}
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