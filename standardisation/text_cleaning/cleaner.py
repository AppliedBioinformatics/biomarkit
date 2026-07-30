"""
Text cleaning module for standardizing research paper markdown files.

Uses regex-first section classification with optional LLM fallback to classify
heading roles, then assembles standardised output containing only core IMRaD
sections (Introduction, Methods, Results, Discussion).
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from config import FINAL_MARKDOWN_DIR
from text_extraction.basemodels.publication import Publication
from standardisation.text_cleaning.section_classifier import classify_headings, Action
from standardisation.text_cleaning.assembler import assemble


@dataclass
class CleaningStats:
    doi: str
    title: str
    publisher: str
    year: int
    document_type: str
    original_size_kb: float
    cleaned_size_kb: float
    tables_removed: int
    figures_removed: int
    latex_removed: int
    h1_count: int   # lines starting with "# "
    h2_count: int   # lines starting with "## "
    status: str     # "success" | "failure"
    removed_sections: list[str] = field(default_factory=list)


class Cleaner:
    """
    Standardizes research paper Markdown files based on input parameter instructions.

    1) Replaces all paper figures with <figure> tag.
    2) Replaces all paper tables with <table> tag.
    3) Replaces all Paper Latex with <latex> tag.
    4) Removes References.

    5a) Passes all paper headers to LLM for major paper section classification.
    5b) Flags headers to remove.
    5c) Flags subheadings to flatten.

    6) Process LLM results to build the final cleaned Markdown file.

    Attributes:
        publications: List of Publication objects to process
        output_dir: Optional directory for cleaned output files
        classifier: Optional SectionClassifierBase instance for LLM classification of headings.
    """

    _TABLE_CAPTION = re.compile(
        r"^\s*\*{0,2}Table\s+[\w]+\*{0,2}[\s|:.].*$",
        re.IGNORECASE,
    )

    # Inline HTML table â€” entire <table>...</table> on one or more lines
    _HTML_TABLE = re.compile(r"<table[\s\S]*?</table>", re.IGNORECASE)

    # Table footnote line: starts with a superscript marker like ^a^ or ^1^
    _TABLE_FOOTNOTE = re.compile(r"^\^[\w]+\^")

    # Display math: $$...$$ â€” may span multiple lines
    _DISPLAY_MATH = re.compile(r"\$\$[\s\S]*?\$\$")
    # Inline math: $...$ â€” single line, non-greedy, must contain at least one char
    _INLINE_MATH = re.compile(r"\$[^\$\n]+\$")

    # Figure caption line â€” matches the start of a caption immediately after an image
    # or a standalone bracketed/plain caption. Covers:
    #   "Fig. 1 ..."  "Fig 1. ..."  "Fig. 1: ..."  "Fig. 1 | ..."
    #   "Figure 1. ..."  "FIGURE 1 | ..."
    _FIGURE_CAPTION_LINE = re.compile(
        r"^\s*\*{0,2}Fig(?:ure)?\.?\s+[\w]+\*{0,2}[\s|:.].*$",
        re.IGNORECASE,
    )
    # Elsevier bracketed caption: [Fig. 1: ...] â€” entire line
    _FIGURE_CAPTION_BRACKETED = re.compile(
        r"^\s*\[Fig(?:ure)?\.?\s+[\w]+[^\]]*\]\s*$",
        re.IGNORECASE,
    )
    # Markdown image embed line: ![...](...) optionally followed by trailing spaces
    _IMAGE_LINE = re.compile(r"^\s*!\[.*?\]\(.*?\)\s*$")

    def __init__(
        self,
        publication_list: list[Publication],
        output_dir: Optional[Path] = None,
        classifier=None,
        cache: Optional[Path] = None,
        keep_latex: bool = False,
        keep_tables: bool = False,
        max_workers: int = 1,
    ):
        logging.debug("Attempting to instantiate cleaner class.")

        self.publications = publication_list
        self.output_dir = output_dir
        self.classifier = classifier
        self.cache = cache
        self.keep_latex = keep_latex
        self.keep_tables = keep_tables
        self.max_workers = max_workers
        self.non_imrad_pattern: dict[str, re.Pattern] = {
            "non_imrad": re.compile(r"^#{3}\s+.+$", re.MULTILINE)
        }

        logging.debug("Cleaner class instantiated.")

    # ------------------------------------------------------------------
    # 1) Strip Figures (always).
    # ------------------------------------------------------------------

    def _remove_sections(
        self, content: str, patterns: dict[str, re.Pattern]
    ) -> tuple[str, list[str]]:
        """Remove sections whose headings match the provided patterns.

        Returns a tuple of (cleaned_content, removed_heading_texts).
        """
        lines = content.split("\n")
        result_lines = []
        removed: list[str] = []
        skip_until_next_section = False
        current_section_level = 0

        for line in lines:
            heading_match = re.match(r"^(#{1,6})\s+(.+)$", line)

            if heading_match:
                heading_level = len(heading_match.group(1))
                heading_text = heading_match.group(2).strip()

                if skip_until_next_section:
                    if heading_level <= current_section_level:
                        skip_until_next_section = False
                    else:
                        continue

                should_remove = False
                for pattern_name, pattern in patterns.items():
                    if pattern.match(line):
                        should_remove = True
                        skip_until_next_section = True
                        current_section_level = heading_level
                        removed.append(heading_text)
                        logging.debug(f"Removing section: {heading_text} (pattern: {pattern_name})")
                        break

                if not should_remove:
                    result_lines.append(line)
            else:
                if skip_until_next_section:
                    if line.startswith("|"):
                        skip_until_next_section = False
                        result_lines.append(line)
                else:
                    result_lines.append(line)

        return "\n".join(result_lines), removed

    @classmethod
    def _replace_latex(cls, content: str, source: str = "") -> str:
        """Replace LaTeX math expressions with <latex_removed>.

        Handles two forms:
        - Display math: $$...$$ (may span multiple lines) â†’ <latex_removed>
        - Inline math:  $...$   (single line)             â†’ <latex_removed>

        Display blocks are replaced first so their $$ delimiters are not
        misidentified as two consecutive inline expressions.

        Args:
            content: Markdown content string.
            source:  Label used in log messages (e.g. file path).

        Returns:
            Content with all LaTeX math expressions replaced by <latex_removed>.
        """
        content, display_count = cls._DISPLAY_MATH.subn("<latex_removed>", content)
        content, inline_count = cls._INLINE_MATH.subn("<latex_removed>", content)

        total = display_count + inline_count
        label = f" in {source}" if source else ""
        logging.debug(
            f"LaTeX replacement{label}: {display_count} display, "
            f"{inline_count} inline ({total} total)"
        )
        logging.info(f"LaTeX replacement{label}: {total} equation(s) replaced with <latex_removed>")

        return content

    @classmethod
    def _emit_table(cls, result: list[str], table_num: int, label: str) -> None:
        """Replace or append <table_removed>, consuming any preceding caption.

        Looks back through `result` past blank lines to find the last non-blank
        line. If it matches a table caption pattern, replaces it (and drops any
        intervening blanks); otherwise appends a fresh tag.
        """
        last_nonblank_idx = next(
            (k for k in range(len(result) - 1, -1, -1) if result[k].strip()),
            None,
        )
        if last_nonblank_idx is not None and cls._TABLE_CAPTION.match(result[last_nonblank_idx]):
            logging.debug(f"Table {table_num}: replacing caption + {label}")
            result[last_nonblank_idx] = "<table_removed>"
            del result[last_nonblank_idx + 1:]
        else:
            logging.debug(f"Table {table_num}: replacing {label} (no caption)")
            result.append("<table_removed>")

    @classmethod
    def _replace_tables(cls, content: str, source: str = "") -> str:
        """Replace markdown and HTML tables (plus any preceding caption) with <table>.

        Handles two table formats:
        - Pipe tables: contiguous lines starting with '|'
        - Inline HTML tables: <table>...</table> (single or multi-line)

        If the line directly before a table block matches a caption pattern
        (e.g. 'Table 1: Description', '**Table 2** | Title'), that line is
        also consumed and replaced by the single '<table>' tag.

        Args:
            content: Markdown content string.
            source:  Label used in log messages (e.g. file path).

        Returns:
            Content with each table block (plus optional caption) replaced by '<table>'.
        """
        # --- Pass 1: collapse inline HTML tables to a single sentinel line ----
        # Replace each <table>...</table> with a unique token so the line-based
        # pass below can treat it uniformly.
        _HTML_SENTINEL = "\x00TABLE\x00"
        content, html_count = cls._HTML_TABLE.subn(_HTML_SENTINEL, content)

        # --- Pass 2: line-by-line scan for pipe tables and HTML sentinels -----
        lines = content.split("\n")
        result: list[str] = []
        i = 0
        table_count = 0

        while i < len(lines):
            line = lines[i]
            is_pipe_table = line.startswith("|")
            is_html_table = _HTML_SENTINEL in line

            if is_pipe_table:
                # Consume entire contiguous pipe-table block
                while i < len(lines) and lines[i].startswith("|"):
                    i += 1
                # Consume trailing footnote lines (^a^ ..., ^b^ ...) separated
                # from the table by at most one blank line
                j = i
                if j < len(lines) and lines[j].strip() == "":
                    j += 1
                while j < len(lines) and cls._TABLE_FOOTNOTE.match(lines[j]):
                    j += 1
                if j > i:
                    i = j
                table_count += 1
                cls._emit_table(result, table_count, "pipe table")

            elif is_html_table:
                # May contain multiple HTML tables on one line â€” count each sentinel
                n = line.count(_HTML_SENTINEL)
                if n == 1:
                    table_count += 1
                    cls._emit_table(result, table_count, "HTML table")
                else:
                    # Multiple tables on one line â€” emit one tag per table
                    for _ in range(n):
                        table_count += 1
                        logging.debug(f"Table {table_count}: replacing HTML table (inline)")
                        result.append("<table_removed>")
                i += 1

            else:
                result.append(line)
                i += 1

        label = f" in {source}" if source else ""
        logging.info(f"Table replacement{label}: {table_count} table(s) replaced with <table>")

        return "\n".join(result)

    @classmethod
    def _replace_figures(cls, content: str, source: str = "") -> str:
        """Replace figure images and captions with <figure>.

        Handles two formats:

        1. PDF-derived (MinerU): a Markdown image line followed (with optional
           blank lines) by a caption line starting with Fig/Figure/FIGURE.
           Both the image line and the caption line are consumed and replaced
           by a single '<figure>' tag.

        2. Elsevier XML-derived: standalone bracketed captions such as
           '[Fig. 1: Some description.]' â€” replaced directly with '<figure>'.

        Args:
            content: Markdown content string.
            source:  Label used in log messages (e.g. file path).

        Returns:
            Content with figure images and captions replaced by '<figure>'.
        """
        lines = content.split("\n")
        result: list[str] = []
        i = 0
        figure_count = 0

        while i < len(lines):
            line = lines[i]

            # --- Format 1: image line (possibly followed by blank lines then caption) ---
            if cls._IMAGE_LINE.match(line):
                # Look ahead past any blank lines for a caption
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1

                if j < len(lines) and cls._FIGURE_CAPTION_LINE.match(lines[j]):
                    # Consume image + blanks + caption â†’ one <figure>
                    figure_count += 1
                    logging.debug(f"Figure {figure_count}: replacing image + caption")
                    result.append("<figure_removed>")
                    i = j + 1
                else:
                    # Image with no following caption â€” keep as-is
                    result.append(line)
                    i += 1

            # --- Format 2: bracketed Elsevier caption (no preceding image line) ---
            elif cls._FIGURE_CAPTION_BRACKETED.match(line):
                figure_count += 1
                logging.debug(f"Figure {figure_count}: replacing bracketed caption")
                result.append("<figure_removed>")
                i += 1

            else:
                result.append(line)
                i += 1

        label = f" in {source}" if source else ""
        logging.info(f"Figure replacement{label}: {figure_count} figure(s) replaced with <figure>")

        return "\n".join(result)

    # ------------------------------------------------------------------
    # Output path
    # ------------------------------------------------------------------

    def _get_output_path(self, publication) -> Path:
        """Return the output path for a cleaned markdown file."""
        raw_md_path = Path(publication.raw_md_filepath)
        cleaned_filename = f"{raw_md_path.stem}.cleaned.md"
        out_dir = self.output_dir if self.output_dir is not None else FINAL_MARKDOWN_DIR
        out_dir.mkdir(parents=True, exist_ok=True)
        return out_dir / cleaned_filename

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @staticmethod
    def extract_headings_from_content(content: str) -> dict[int, str]:
        """Return a {line_number: heading_text} map for all '#' lines in a content string."""
        headings: dict[int, str] = {}
        for i, line in enumerate(content.splitlines(), start=1):
            if line.startswith("#"):
                headings[i] = line
        return headings

    @staticmethod
    def _apply_heading_levels(content: str, levels: dict) -> str:
        """Rewrite the '#' prefix of each classified heading, preserving heading text.

        Args:
            content: Markdown content string.
            levels:  {line_number_str: level} where level is "#", "##", "###", or "####".

        Returns:
            Updated content string.
        """
        lines = content.splitlines()
        for line_str, level in levels.items():
            idx = int(line_str) - 1
            if 0 <= idx < len(lines):
                # Strip existing hashes and reapply the classified level
                text = re.sub(r"^#{1,6}\s*", "", lines[idx])
                lines[idx] = f"{level} {text}"
        return "\n".join(lines)

    def remove_boilerplate(self, publication) -> CleaningStats:
        """Identify IMRaD sections and extract only scientific content."""
        _doi = getattr(publication, "doi", None)
        _title = getattr(publication, "title", None)
        _publisher = getattr(publication, "publisher", None)
        _year = getattr(publication, "year", None)
        _document_type = getattr(publication, "document_type", None)
        doi = _doi if isinstance(_doi, str) else "unknown"
        title = _title if isinstance(_title, str) else "unknown"
        publisher = _publisher if isinstance(_publisher, str) else "unknown"
        year = _year if isinstance(_year, int) else 0
        document_type = _document_type if isinstance(_document_type, str) else "unknown"

        def _failure_stats() -> CleaningStats:
            return CleaningStats(
                doi=doi, title=title, publisher=publisher, year=year,
                document_type=document_type, original_size_kb=0.0,
                cleaned_size_kb=0.0, tables_removed=0, figures_removed=0,
                latex_removed=0, h1_count=0, h2_count=0, status="failure",
                removed_sections=[],
            )

        try:
            raw_md_path = Path(publication.raw_md_filepath)
            original_size_kb = raw_md_path.stat().st_size / 1024
            content = raw_md_path.read_text(encoding="utf-8")

            logging.debug(f"Processing {publication.raw_md_filepath}")

            # --- Step 1: Pre-process content (always applied) ---
            source = str(publication.publication_filepath)
            if not self.keep_latex:
                content = self._replace_latex(content, source=source)
            if not self.keep_tables:
                content = self._replace_tables(content, source=source)
            content = self._replace_figures(content, source=source)

            # --- Step 2: Extract headings and classify via regex ---
            headings = self.extract_headings_from_content(content)
            classification = classify_headings(headings)

            # --- Step 2b: Detect merged abstract+introduction ---
            abstract_text = getattr(publication, "abstract", None)
            if abstract_text:
                from standardisation.text_cleaning.abstract_splitter import find_intro_after_abstract
                content_lines = content.split("\n")
                intro_line = find_intro_after_abstract(
                    content_lines, classification, abstract_text
                )
                if intro_line is not None:
                    classification[intro_line] = Action.INTRODUCTION
                    logging.info(
                        f"Inserted synthetic Introduction at line {intro_line} for {doi}"
                    )

            # --- Step 2c: Infer implicit introduction ---
            # If no Introduction heading was found but Methods exists, treat
            # the body text between the last DELETE/title heading and Methods
            # as Introduction.
            has_intro = any(a == Action.INTRODUCTION for a in classification.actions.values())
            if not has_intro:
                methods_line = None
                for ln, a in sorted(classification.actions.items()):
                    if a == Action.METHODS:
                        methods_line = ln
                        break
                if methods_line is not None:
                    content_lines = content.split("\n")
                    # Find the first non-empty body line before Methods
                    # that comes after the last DELETE heading before Methods
                    last_delete_before_methods = 0
                    for ln, a in sorted(classification.actions.items()):
                        if ln >= methods_line:
                            break
                        if a == Action.DELETE:
                            last_delete_before_methods = ln

                    # Scan forward from last delete to find first body content
                    for candidate in range(last_delete_before_methods + 1, methods_line):
                        idx = candidate - 1
                        if idx < len(content_lines):
                            line = content_lines[idx].strip()
                            # Skip blank lines and heading lines
                            if line and not re.match(r"^#{1,6}\s+", content_lines[idx]):
                                classification[candidate] = Action.INTRODUCTION
                                logging.info(
                                    f"Inferred implicit Introduction at line {candidate} for {doi}"
                                )
                                break

            # --- Step 3: LLM fallback for unresolved headings ---
            removed_sections: list[str] = []
            if classification.unresolved and self.classifier is not None:
                llm_result = self.classifier.classify(classification.unresolved)
                if llm_result:
                    # Convert LLM string actions to Action enum
                    _ACTION_MAP = {a.value: a for a in Action}
                    for line_str, action_str in llm_result.items():
                        action = _ACTION_MAP.get(action_str)
                        if action is not None:
                            classification[int(line_str)] = action
                        else:
                            logging.warning(
                                f"Unknown LLM action {action_str!r} for line {line_str}"
                            )
                else:
                    logging.warning(
                        f"LLM classification failed for {publication.publication_filepath}, "
                        "unresolved headings will be treated as body text"
                    )

            # Treat any still-unresolved headings as body text
            for line_num in list(classification.unresolved.keys()):
                if line_num not in classification.actions:
                    classification[line_num] = Action.BODY

            # --- Step 4: Assemble standardised output ---
            content = assemble(content, classification.actions)

            # Track which sections were deleted
            for line_num, action in classification.actions.items():
                if action == Action.DELETE and line_num in headings:
                    heading_text = re.sub(r"^#{1,6}\s*", "", headings[line_num])
                    removed_sections.append(heading_text)

            tables_removed = content.count("<table_removed>")
            figures_removed = content.count("<figure_removed>")
            latex_removed = content.count("<latex_removed>")
            lines = content.splitlines()
            h1_count = sum(1 for ln in lines if ln.startswith("# "))
            h2_count = sum(1 for ln in lines if ln.startswith("## "))

            output_path = self._get_output_path(publication)

            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write(content)

            cleaned_size_kb = output_path.stat().st_size / 1024
            logging.info(f"Cleaned content saved to {output_path}")

            publication.final_md_filepath = output_path

            if self.cache is not None:
                from text_extraction.database.database import update_final_md_filepath
                update_final_md_filepath(
                    doi=doi,
                    final_md_filepath=str(output_path),
                    db_path=self.cache,
                )
                logging.info(f"Cache updated with final_md_filepath for {doi}")

            return CleaningStats(
                doi=doi, title=title, publisher=publisher, year=year,
                document_type=document_type, original_size_kb=original_size_kb,
                cleaned_size_kb=cleaned_size_kb, tables_removed=tables_removed,
                figures_removed=figures_removed, latex_removed=latex_removed,
                h1_count=h1_count, h2_count=h2_count, status="success",
                removed_sections=removed_sections,
            )

        except FileNotFoundError:
            logging.error(f"Raw markdown file not found: {publication.raw_md_filepath}")
            return _failure_stats()
        except Exception as exc:
            logging.error(f"Error processing {getattr(publication, 'raw_md_filepath', 'unknown')}: {exc}")
            return _failure_stats()

    @staticmethod
    def _stats_from_cache(publication) -> CleaningStats:
        """Build CleaningStats from an already-cleaned publication without re-processing."""
        doi = getattr(publication, "doi", "unknown")
        base = dict(
            doi=doi,
            title=getattr(publication, "title", "unknown"),
            publisher=getattr(publication, "publisher", "unknown"),
            year=getattr(publication, "year", 0),
            document_type=str(getattr(publication, "document_type", "unknown")),
        )
        try:
            original_size_kb = Path(publication.raw_md_filepath).stat().st_size / 1024
            cleaned_size_kb = Path(publication.final_md_filepath).stat().st_size / 1024
            cleaned_content = Path(publication.final_md_filepath).read_text(encoding="utf-8")
            lines = cleaned_content.splitlines()
            logging.debug(f"[Cleaner] Cache hit for {doi} â€” skipping re-clean.")
            return CleaningStats(
                **base,
                original_size_kb=original_size_kb,
                cleaned_size_kb=cleaned_size_kb,
                tables_removed=cleaned_content.count("<table_removed>"),
                figures_removed=cleaned_content.count("<figure_removed>"),
                latex_removed=cleaned_content.count("<latex_removed>"),
                h1_count=sum(1 for ln in lines if ln.startswith("# ")),
                h2_count=sum(1 for ln in lines if ln.startswith("## ")),
                status="success",
            )
        except Exception as exc:
            logging.warning(f"[Cleaner] Cache hit for {doi} but could not read files: {exc}")
            return CleaningStats(
                **base,
                original_size_kb=0.0, cleaned_size_kb=0.0,
                tables_removed=0, figures_removed=0, latex_removed=0,
                h1_count=0, h2_count=0, status="failure",
            )

    def clean_all(self) -> tuple[list[CleaningStats], list[CleaningStats]]:
        """Process all publications.

        Uses a thread pool (sized by ``self.max_workers``) to parallelise the
        LLM-bound cleaning work.  When ``max_workers=1`` behaviour is identical
        to the previous sequential loop.

        Returns:
            A tuple of (successes, failures) where each is a list of CleaningStats objects.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from tqdm import tqdm

        successes: list[CleaningStats] = []
        failures: list[CleaningStats] = []
        total = len(self.publications)

        logging.info(f"Starting cleaning for {total} publications (max_workers={self.max_workers})")

        # Separate cached from uncached so cached pubs don't occupy a thread.
        cached_pubs = [p for p in self.publications if p.final_md_filepath is not None]
        uncached_pubs = [p for p in self.publications if p.final_md_filepath is None]

        cached = len(cached_pubs)
        for pub in cached_pubs:
            stats = self._stats_from_cache(pub)
            (successes if stats.status == "success" else failures).append(stats)

        with tqdm(total=total, unit="paper", desc="Cleaning", initial=cached) as bar:
            bar.set_postfix(ok=len(successes), failed=len(failures), cached=cached)

            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = {pool.submit(self.remove_boilerplate, pub): pub for pub in uncached_pubs}

                for future in as_completed(futures):
                    stats = future.result()
                    if stats.status == "success":
                        successes.append(stats)
                    else:
                        failures.append(stats)

                    bar.set_postfix(ok=len(successes), failed=len(failures), cached=cached)
                    bar.update(1)

        logging.info(
            f"Completed: {len(successes)}/{total} succeeded ({cached} from cache), {len(failures)} failed"
        )
        if failures:
            logging.warning(
                "Failed publications:\n"
                + "\n".join(f"  {s.doi}" for s in failures)
            )

        return successes, failures


if __name__ == "__main__":
    import sys
    from unittest.mock import Mock

    sys.path.append(str(Path(__file__).parent.parent.parent))
    from config import RAW_MARKDOWN_DIR, TMP_DIR
    from standardisation.llms.providers.llama_section_classifier import LlamaSectionClassifier

    SAMPLE_SIZE = 30
    OUTPUT_DIR = TMP_DIR / "cleaner_test"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    markdown_files = list(Path(RAW_MARKDOWN_DIR).rglob("*.md"))[:SAMPLE_SIZE]
    print(f"Processing {len(markdown_files)} of {SAMPLE_SIZE} markdown files")

    mock_publications = []
    for file_path in markdown_files:
        pub = Mock()
        pub.publication_filepath = file_path.with_suffix(".pdf")
        pub.raw_md_filepath = file_path
        mock_publications.append(pub)

    classifier = LlamaSectionClassifier()
    cleaner = Cleaner(mock_publications, output_dir=OUTPUT_DIR, classifier=classifier)

    print(f"Writing cleaned files to {OUTPUT_DIR}\n")
    ok, failed = cleaner.clean_all()

    print(f"\nDone. {len(ok)}/{len(markdown_files)} files cleaned successfully.")
    if failed:
        print(f"{len(failed)} failures:")
        for s in failed:
            print(f"  {s.doi}")