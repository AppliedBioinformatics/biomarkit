import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from text_extraction.basemodels.publication import Publication
from standardisation.content_list.schema import (
    Document, TitleBlock, TitleContent, TextSpan, ParagraphBlock,
)
from standardisation.content_list.filters import (
    remove_boilerplate,
    remove_figures,
    remove_latex,
    remove_references,
    remove_tables,
)
from standardisation.content_list.renderer import render
from standardisation.llms.llm_classifier import LlamaClassifier
from config import FINAL_MARKDOWN_DIR
from text_extraction.database.database import update_final_md_filepath

# Strips leading section numbering (e.g. "1.", "II.", "§3") before matching heading text.
_SECTION_PREFIX_RE = re.compile(r'^[\d\s.\-–—\xa7IVXivx]+')
_INTRO_RE = re.compile(r'^(introduction|background)\b')
_METHODS_RE = re.compile(
    r'^(methods|materials\s+(?:and|&)\s+methods|methodology'
    r'|experimental(?:\s+section)?|patients\s+and\s+methods|study\s+design)\b'
)
_RESULTS_RE = re.compile(r'^(results|findings|outcomes)\b')
_RESULTS_AND_DISCUSSION_RE = re.compile(r'^results\s+(?:and|&)\s+discussion\b')
_DISCUSSION_RE = re.compile(
    r'^(discussion|conclusions?\s+and\s+discussion|discussion\s+and\s+conclusions?)\b'
)


class Cleaner:
    def __init__(
        self,
        publications: List[Publication],
        context: Dict,
        cache: Optional[Path] = None,
    ):
        self.publications = publications
        self.cache = cache
        self.keep_figures = context["keep_figures"]
        self.keep_tables = context["keep_tables"]
        self.keep_latex = context["keep_latex"]
        self.keep_references = context["keep_references"]
        self.force_imrad_structure = context["force_imrad_structure"]

    def _truncate_core_text(self, blocks):
        pass

    # --- Shared heading helpers ---

    @staticmethod
    def _normalise_heading(block: TitleBlock) -> str:
        return _SECTION_PREFIX_RE.sub("", block.content.text.lower()).strip()

    @staticmethod
    def _rename_heading(block: TitleBlock, name: str) -> None:
        block.content.title_content = [TextSpan(type="text", content=name)]

    # --- Section detectors ---

    @staticmethod
    def _is_intro_heading(block: TitleBlock) -> bool:
        return bool(_INTRO_RE.match(Cleaner._normalise_heading(block)))

    @staticmethod
    def _is_methods_heading(block: TitleBlock) -> bool:
        return bool(_METHODS_RE.match(Cleaner._normalise_heading(block)))

    @staticmethod
    def _is_results_heading(block: TitleBlock) -> bool:
        return bool(_RESULTS_RE.match(Cleaner._normalise_heading(block)))

    @staticmethod
    def _is_results_and_discussion_heading(block: TitleBlock) -> bool:
        return bool(_RESULTS_AND_DISCUSSION_RE.match(Cleaner._normalise_heading(block)))

    @staticmethod
    def _is_discussion_heading(block: TitleBlock) -> bool:
        return bool(_DISCUSSION_RE.match(Cleaner._normalise_heading(block)))

    # --- Block insertion helpers (introduction only — other sections never insert) ---

    @staticmethod
    def _make_introduction_heading(bbox) -> TitleBlock:
        return TitleBlock(
            type="title",
            content=TitleContent(
                title_content=[TextSpan(type="text", content="Introduction")],
                level=1,
            ),
            bbox=bbox,
        )

    @staticmethod
    def _make_end_marker(bbox) -> TitleBlock:
        return TitleBlock(
            type="title",
            content=TitleContent(
                title_content=[TextSpan(type="text", content="end")],
                level=1,
            ),
            bbox=bbox,
        )

    @staticmethod
    def _insert_intro_heading(blocks, index: int) -> list:
        intro_block = blocks[index]
        if isinstance(intro_block, TitleBlock):
            Cleaner._rename_heading(intro_block, "Introduction")
            return blocks
        new_heading = Cleaner._make_introduction_heading(intro_block.bbox)
        return blocks[:index] + [new_heading] + blocks[index:]

    @staticmethod
    def _insert_end_marker(blocks, index: int) -> list:
        end_block = blocks[index]
        if isinstance(end_block, TitleBlock):
            Cleaner._rename_heading(end_block, "end")
            return blocks
        marker = Cleaner._make_end_marker(end_block.bbox)
        return blocks[:index] + [marker] + blocks[index:]

    # --- LLM context builders ---

    @staticmethod
    def _build_llm_context(blocks) -> dict[int, str]:
        context: dict[int, str] = {}
        for i, block in enumerate(blocks):
            if isinstance(block, TitleBlock):
                context[i] = "[heading] " + block.content.text
            elif isinstance(block, ParagraphBlock):
                text = "".join(
                    span.content for span in block.content.paragraph_content
                    if isinstance(span.content, str)
                )
                context[i] = "[paragraph] " + text[:50]
        return context

    @staticmethod
    def _build_headings_context(blocks) -> dict[int, str]:
        return {
            i: "[heading] " + block.content.text
            for i, block in enumerate(blocks)
            if isinstance(block, TitleBlock)
        }

    @staticmethod
    def _trim_to_core_text(blocks) -> list:
        intro_idx = next(
            (i for i, b in enumerate(blocks)
             if isinstance(b, TitleBlock) and b.content.text == "Introduction"),
            None,
        )
        end_idx = next(
            (i for i, b in enumerate(blocks)
             if isinstance(b, TitleBlock) and b.content.text == "end"),
            None,
        )
        start = intro_idx if intro_idx is not None else 0
        stop = end_idx if end_idx is not None else len(blocks)
        return blocks[start:stop]

    # --- IMRAD structure methods ---
    def _find_introduction_start(self, blocks) -> list:
        for block in blocks:
            if isinstance(block, TitleBlock) and self._is_intro_heading(block):
                logging.info("[Cleaner] Introduction found via regex")
                self._rename_heading(block, "Introduction")
                return blocks

        blocks_context = self._build_llm_context(blocks[:100])
        if not blocks_context:
            logging.warning("[Cleaner] find_introduction_start: no headings or paragraphs found")
            return blocks

        intro_index = LlamaClassifier().classify_intro(blocks_context)
        if intro_index is not None:
            logging.info("[Cleaner] Introduction found via LLM at block index %d", intro_index)
            return self._insert_intro_heading(blocks, intro_index)

        logging.warning("[Cleaner] find_introduction_start: LLM could not identify introduction")
        return blocks

    def _find_core_text_end(self, blocks) -> list:
        blocks_context = self._build_headings_context(blocks)
        if not blocks_context:
            logging.warning("[Cleaner] find_core_text_end: no headings found")
            return blocks

        end_index = LlamaClassifier().classify_end(blocks_context)
        if end_index is not None:
            logging.info("[Cleaner] Core text end found via LLM at block index %d", end_index)
            return self._insert_end_marker(blocks, end_index)

        logging.warning("[Cleaner] find_core_text_end: LLM could not identify end of core text")
        return blocks

    def _enforce_imrad_headings(self, blocks) -> list:
        headings_context = self._build_headings_context(blocks)

        # Methods (required)
        methods_found = False
        for block in blocks:
            if isinstance(block, TitleBlock) and self._is_methods_heading(block):
                logging.info("[Cleaner] Methods heading found via regex")
                self._rename_heading(block, "Methods")
                methods_found = True
                break
        if not methods_found and headings_context:
            idx = LlamaClassifier().classify_methods(headings_context)
            if idx is not None and isinstance(blocks[idx], TitleBlock):
                logging.info("[Cleaner] Methods heading found via LLM at block index %d", idx)
                self._rename_heading(blocks[idx], "Methods")
                methods_found = True
        if not methods_found:
            logging.warning("[Cleaner] enforce_imrad_headings: could not find Methods heading")

        # Results (required) — combined "Results and Discussion" also satisfies Discussion
        results_found = False
        discussion_found = False
        for block in blocks:
            if not isinstance(block, TitleBlock):
                continue
            if self._is_results_and_discussion_heading(block):
                logging.info("[Cleaner] Combined Results and Discussion heading found via regex")
                results_found = True
                discussion_found = True
                break
            if self._is_results_heading(block):
                logging.info("[Cleaner] Results heading found via regex")
                self._rename_heading(block, "Results")
                results_found = True
                break
        if not results_found and headings_context:
            idx = LlamaClassifier().classify_results(headings_context)
            if idx is not None and isinstance(blocks[idx], TitleBlock):
                logging.info("[Cleaner] Results heading found via LLM at block index %d", idx)
                self._rename_heading(blocks[idx], "Results")
                results_found = True
        if not results_found:
            logging.warning("[Cleaner] enforce_imrad_headings: could not find Results heading")

        # Discussion (optional — absence is not a warning)
        if not discussion_found:
            for block in blocks:
                if isinstance(block, TitleBlock) and self._is_discussion_heading(block):
                    logging.info("[Cleaner] Discussion heading found via regex")
                    self._rename_heading(block, "Discussion")
                    discussion_found = True
                    break
            if not discussion_found and headings_context:
                idx = LlamaClassifier().classify_discussion(headings_context)
                if idx is not None and isinstance(blocks[idx], TitleBlock):
                    logging.info("[Cleaner] Discussion heading found via LLM at block index %d", idx)
                    self._rename_heading(blocks[idx], "Discussion")
                else:
                    logging.info("[Cleaner] enforce_imrad_headings: no Discussion heading found (optional)")

        return blocks

    def _build_imrad_structure(self, blocks) -> list:
        blocks = self._find_introduction_start(blocks)
        blocks = self._find_core_text_end(blocks)
        blocks = self._trim_to_core_text(blocks)
        blocks = self._enforce_imrad_headings(blocks)
        return blocks

    def clean_from_json(self, pub: Publication):
        """
        Cleans and processes a publication's content from its JSON structure file into markdown format.

        The method processes the content of a given publication's JSON file by first applying transformations such as
        removing boilerplate blocks, references, figures, tables, and LaTeX, based on user preferences.
        Additionally, it supports optional restructuring of content into the IMRaD (Introduction, Methods, Results,
        and Discussion) structure.

        Processed content is rendered into markdown format, saved to a specified directory,
        and updates the publication's cache with the markdown file path if caching is enabled.

        Parameters:
            pub (Publication): The publication object containing paths and metadata required
                for processing its content.

        Returns:
            str: The final processed content in markdown format.
        """
        json_path = Path(pub.content_json_filepath)
        doc = Document.from_file(json_path)

        # Non-optional boilerplate block removals.
        blocks = remove_boilerplate(doc.blocks())

        # Optional filters depending on user preferences.
        if not self.keep_references:
            blocks = remove_references(blocks)
        if not self.keep_figures:
            blocks = remove_figures(blocks)
        if not self.keep_tables:
            blocks = remove_tables(blocks)
        if not self.keep_latex:
            blocks = remove_latex(blocks)

        if self.force_imrad_structure:
            blocks = self._build_imrad_structure(blocks)

        # Render final markdown from the blocks, save it and update cache accordingly.
        markdown = render(blocks)
        stem = Path(pub.publication_filepath).stem
        FINAL_MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
        output_path = FINAL_MARKDOWN_DIR / f"{stem}.md"
        output_path.write_text(markdown, encoding="utf-8")

        # Add to cache.
        pub.final_md_filepath = output_path
        if self.cache:
            update_final_md_filepath(pub.doi, str(output_path), self.cache)

        return markdown

    def clean_all(self):
        """
        Cleans all publication objects in self.publications

        This method iterates through a collection of publications and initiates
        a cleaning operation for each publication by calling the `clean_from_json`
        method.

        Args:
            None

        Returns:
            None
        """
        for publication in self.publications:
            self.clean_from_json(pub=publication)