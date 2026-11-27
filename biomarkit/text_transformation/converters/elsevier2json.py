"""
Parse Elsevier full-text XML articles into content_list_v2.json block format.
Provides standalone parsing helpers and ElsevierXmlTransformer for use within
the text-transformation pipeline. Page furniture, footnotes and publication dates are not extracted, so
keep_boilerplate has nothing to remove from Elsevier output.
"""

import functools
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor, as_completed
from html import escape as html_escape
from pathlib import Path
from typing import List, Optional

from tqdm import tqdm

from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_download.utils.generics import progress_split_bar
from biomarkit.text_transformation.converters.ABC.transformer import Transformer


# ---------------------------------------------------------------------------
# Elsevier XML namespaces
# ---------------------------------------------------------------------------

NS = {
    "ce": "http://www.elsevier.com/xml/common/dtd",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "prism": "http://prismstandard.org/namespaces/basic/2.0/",
    "ja": "http://www.elsevier.com/xml/ja/dtd",
    "sb": "http://www.elsevier.com/xml/common/struct-bib/dtd",
    "mml": "http://www.w3.org/1998/Math/MathML",
    "xocs": "http://www.elsevier.com/xml/xocs/dtd",
    "sa": "http://www.elsevier.com/xml/common/struct-aff/dtd",
    "cals": "http://www.elsevier.com/xml/common/cals/dtd",
    "xlink": "http://www.w3.org/1999/xlink",
    "bk": "http://www.elsevier.com/xml/bk/dtd",
    "tb": "http://www.elsevier.com/xml/common/table/dtd",
    "default": "http://www.elsevier.com/xml/svapi/article/dtd",
}


# MathML token symbols -> LaTeX. Single-character keys, so str.translate gives the same result as chained replaces.
_MATHML_LATEX = str.maketrans({
    "∑": r"\sum", "∏": r"\prod", "∫": r"\int", "≈": r"\approx", "≠": r"\neq",
    "≤": r"\leq", "≥": r"\geq", "±": r"\pm", "∞": r"\infty",
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\epsilon",
    "θ": r"\theta", "λ": r"\lambda", "μ": r"\mu", "π": r"\pi", "ρ": r"\rho",
    "σ": r"\sigma", "τ": r"\tau", "φ": r"\phi", "χ": r"\chi", "ω": r"\omega",
})


@functools.lru_cache(maxsize=None)
def _ns(tag: str) -> str:
    """Expand a namespace-prefixed tag like 'ce:para' to '{uri}para'."""
    if ":" in tag:
        prefix, local = tag.split(":", 1)
        uri = NS.get(prefix, "")
        return f"{{{uri}}}{local}"
    return tag


def _local(tag: str) -> str:
    """Strip the namespace from a tag: '{uri}para' -> 'para'."""
    return tag.rsplit("}", 1)[-1]


@functools.lru_cache(maxsize=None)
def _xpath(path: str) -> str:
    """Expand a colon-prefixed path like 'ce:caption/ce:simple-para' to its namespaced form."""
    return "/".join(_ns(p) if p not in (".", "..") else p for p in path.split("/"))


def _find(elem: ET.Element, path: str) -> Optional[ET.Element]:
    """Find element using colon-prefixed namespace path."""
    return elem.find(_xpath(path))


def _findall(elem: ET.Element, path: str) -> List[ET.Element]:
    """Find all elements using colon-prefixed namespace path."""
    return elem.findall(_xpath(path))


def clean_text(text: str) -> str:
    """Normalise whitespace in text."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_SELF_PARSED_TAGS = frozenset({"float-anchor", "display", "math", "formula"})


def get_element_text(elem: ET.Element) -> str:
    """Recursively extract and format text from an element, handling inline markup."""
    if elem is None:
        return ""

    parts: List[str] = []

    # Add element's own text
    if elem.text:
        parts.append(elem.text)

    # Process children
    for child in elem:
        child_local = _local(child.tag)
        # These branches parse the child themselves (or skip it), so its plain text isn't needed.
        child_text = "" if child_local in _SELF_PARSED_TAGS else get_element_text(child)

        if child_local == "italic":
            if child_text.strip():
                parts.append(f"_{child_text}_")
            else:
                parts.append(child_text)
        elif child_local == "bold":
            if child_text.strip():
                parts.append(f"**{child_text}**")
            else:
                parts.append(child_text)
        elif child_local == "sup":
            parts.append(f"^{child_text}^")
        elif child_local == "inf":
            parts.append(f"_{child_text}")
        elif child_local == "cross-ref":
            # Keep citation text as-is
            parts.append(child_text)
        elif child_local == "float-anchor":
            # Skip float anchors (figure/table placement markers)
            pass
        elif child_local == "display":
            formula_text = _extract_formula(child)
            if formula_text:
                parts.append(f"\n\n{formula_text}\n\n")
        elif child_local == "math":
            latex_content = _parse_mathml(child)
            # Add inline math delimiters for math elements within text
            parts.append(f"${latex_content}$")
        elif child_local == "formula":
            parts.append(_extract_formula(child))
        elif child_local in ("label", "section-title"):
            # These are handled at section level, skip here
            parts.append(child_text)
        else:
            parts.append(child_text)

        # Add tail text (text after the closing tag of child)
        if child.tail:
            parts.append(child.tail)

    return "".join(parts)


def _parse_mathml(elem: ET.Element) -> str:
    """Convert MathML element to LaTeX representation."""
    local = _local(elem.tag)

    if local in ("mi", "mn", "mo", "mtext"):
        text = (elem.text or "").strip()
        tail = ""
        # Process children (some mi/mn can have children)
        for child in elem:
            tail += _parse_mathml(child)
            if child.tail:
                tail += child.tail

        # Convert special mathematical operators to LaTeX
        combined = text + tail
        return combined.translate(_MATHML_LATEX)

    if local == "msub":
        children = list(elem)
        if len(children) >= 2:
            base = _parse_mathml(children[0])
            sub = _parse_mathml(children[1])
            return f"{base}_{{{sub}}}"

    if local == "msup":
        children = list(elem)
        if len(children) >= 2:
            base = _parse_mathml(children[0])
            sup = _parse_mathml(children[1])
            return f"{base}^{{{sup}}}"

    if local == "msubsup":
        children = list(elem)
        if len(children) >= 3:
            base = _parse_mathml(children[0])
            sub = _parse_mathml(children[1])
            sup = _parse_mathml(children[2])
            return f"{base}_{{{sub}}}^{{{sup}}}"

    if local == "mfrac":
        children = list(elem)
        if len(children) >= 2:
            num = _parse_mathml(children[0])
            den = _parse_mathml(children[1])
            return rf"\frac{{{num}}}{{{den}}}"

    if local == "mrow":
        parts = []
        if elem.text:
            parts.append(elem.text)
        for child in elem:
            parts.append(_parse_mathml(child))
            if child.tail:
                parts.append(child.tail)
        return "".join(parts)

    if local == "msqrt":
        inner = ""
        for child in elem:
            inner += _parse_mathml(child)
        return rf"\sqrt{{{inner}}}"

    if local == "mroot":
        children = list(elem)
        if len(children) >= 2:
            base = _parse_mathml(children[0])
            index = _parse_mathml(children[1])
            return rf"\sqrt[{index}]{{{base}}}"

    if local == "munder":
        children = list(elem)
        if len(children) >= 2:
            base = _parse_mathml(children[0])
            under = _parse_mathml(children[1])
            return f"{base}_{{{under}}}"

    if local == "mover":
        children = list(elem)
        if len(children) >= 2:
            base = _parse_mathml(children[0])
            over = _parse_mathml(children[1])
            return f"{base}^{{{over}}}"

    if local == "munderover":
        children = list(elem)
        if len(children) >= 3:
            base = _parse_mathml(children[0])
            under = _parse_mathml(children[1])
            over = _parse_mathml(children[2])
            return f"{base}_{{{under}}}^{{{over}}}"

    if local == "mtable":
        # Handle matrices/tables
        rows = []
        for child in elem:
            if _local(child.tag) == "mtr":
                row_cells = []
                for cell in child:
                    if _local(cell.tag) == "mtd":
                        row_cells.append(_parse_mathml(cell))
                if row_cells:
                    rows.append(" & ".join(row_cells))
        if rows:
            return rf"\begin{{pmatrix}} {' \\\\ '.join(rows)} \end{{pmatrix}}"

    if local == "mfenced":
        # Handle parentheses, brackets, etc.
        open_char = elem.get("open", "(")
        close_char = elem.get("close", ")")
        inner = ""
        for child in elem:
            inner += _parse_mathml(child)

        # Convert to LaTeX delimiters if appropriate
        if open_char == "(" and close_char == ")":
            return f"\\left({inner}\\right)"
        elif open_char == "[" and close_char == "]":
            return f"\\left[{inner}\\right]"
        elif open_char == "{" and close_char == "}":
            return f"\\left\\{{{inner}\\right\\}}"
        else:
            return f"{open_char}{inner}{close_char}"

    # Fallback: extract all text
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in elem:
        parts.append(_parse_mathml(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_formula(elem: ET.Element) -> str:
    """Extract formula from a ce:display or ce:formula element with LaTeX formatting."""
    # Look for MathML
    math = None
    for descendant in elem.iter():
        local = _local(descendant.tag)
        if local == "math":
            math = descendant
            break

    # Display (block) or inline formula.
    parent_tag = _local(elem.tag)

    if math is not None:
        latex_content = _parse_mathml(math)
    else:
        # No MathML: convert the plain text. Formulas that are only an image link have no text.
        latex_content = _enhance_text_formulas(clean_text("".join(elem.itertext())))
        if not latex_content:
            return ""

    if parent_tag == "display":
        return f"$$\n{latex_content}\n$$"
    return f"${latex_content}$"


_GREEK_WORDS = {
    'alpha': r'\alpha', 'beta': r'\beta', 'gamma': r'\gamma', 'delta': r'\delta',
    'epsilon': r'\epsilon', 'theta': r'\theta', 'lambda': r'\lambda', 'mu': r'\mu',
    'pi': r'\pi', 'rho': r'\rho', 'sigma': r'\sigma', 'tau': r'\tau',
    'phi': r'\phi', 'chi': r'\chi', 'omega': r'\omega',
}
_GREEK_WORD_RE = re.compile(r'\b(' + '|'.join(_GREEK_WORDS) + r')\b', re.IGNORECASE)
_TEXT_SYMBOLS = str.maketrans({
    '±': r'\pm', '∑': r'\sum', '∏': r'\prod', '∫': r'\int', '≈': r'\approx', '≠': r'\neq',
    '≤': r'\leq', '≥': r'\geq', '∞': r'\infty', 'Σ': r'\Sigma', 'Π': r'\Pi',
    '⌊': r'\lfloor', '⌋': r'\rfloor', '⌈': r'\lceil', '⌉': r'\rceil', '∂': r'\partial',
    '∇': r'\nabla', '∀': r'\forall', '∃': r'\exists', '∈': r'\in', '∉': r'\notin',
    '⊂': r'\subset', '⊃': r'\supset', '⊆': r'\subseteq', '⊇': r'\supseteq',
    '∩': r'\cap', '∪': r'\cup', '×': r'\times', '÷': r'\div', '√': r'\sqrt{}',
    '∴': r'\therefore', '∵': r'\because',
})


def _enhance_text_formulas(text: str) -> str:
    """
    Convert plain-text formula content (from a ce:formula/ce:display without MathML) to LaTeX. Adds no $ delimiters:
    the caller wraps the whole formula once, so it stays a single inline-equation span.
    """
    if not text:
        return text
    text = re.sub(r'(\w+)_(\w+)', r'\1_{\2}', text)
    text = re.sub(r'(\w+)\^(\w+)', r'\1^{\2}', text)
    text = _GREEK_WORD_RE.sub(lambda m: _GREEK_WORDS[m.group(1).lower()], text)
    return text.translate(_TEXT_SYMBOLS)


def extract_title(root: ET.Element) -> str:
    """Extract article title."""
    # Try from article head first (more accurate)
    for article in root.iter(_ns("ja:article")):
        head = article.find(_ns("ja:head"))
        if head is None:
            # head might be unnamespaced inside article
            for child in article:
                child_local = _local(child.tag)
                if child_local == "head":
                    head = child
                    break
        if head is not None:
            title_elem = _find(head, "ce:title")
            if title_elem is not None:
                return clean_text(get_element_text(title_elem))

    # Try from simple-article
    for article in root.iter(_ns("ja:simple-article")):
        for child in article:
            child_local = _local(child.tag)
            if child_local in ("simple-head", "head"):
                title_elem = _find(child, "ce:title")
                if title_elem is not None:
                    return clean_text(get_element_text(title_elem))

    # Fallback: look in any head element
    for head in root.iter():
        local = _local(head.tag)
        if local == "head":
            title_elem = _find(head, "ce:title")
            if title_elem is not None:
                return clean_text(get_element_text(title_elem))

    # Last resort: coredata dc:title
    title = _find(root, "default:coredata/dc:title")
    if title is not None:
        return clean_text(title.text or "")
    # Try without default namespace
    for elem in root.iter():
        local = _local(elem.tag)
        if local == "coredata":
            for child in elem:
                child_local = _local(child.tag)
                if child_local == "title":
                    return clean_text(child.text or "")
    return ""


def extract_abstract(root: ET.Element) -> str:
    """Extract the abstract text."""
    # Look for ce:abstract with class="author" (the main abstract)
    for abstract in root.iter(_ns("ce:abstract")):
        cls = abstract.get("class", "")
        if cls == "graphical":
            continue  # Skip graphical abstract
        # Get section title if present
        paras = []
        for sec in abstract.iter(_ns("ce:abstract-sec")):
            for para in sec.iter(_ns("ce:simple-para")):
                text = clean_text(get_element_text(para))
                if text:
                    paras.append(text)
        if paras:
            return "\n\n".join(paras)

    # Fallback: dc:description from coredata
    for elem in root.iter():
        local = _local(elem.tag)
        if local == "description" and elem.text:
            return clean_text(elem.text)

    return ""


def _parse_cals_tgroup(tgroup: ET.Element):
    """Parse CALS tgroup into header and body rows."""
    header_cells: List[str] = []
    body_rows: List[List[str]] = []

    for child in tgroup.iter():
        child_local = _local(child.tag)

        if child_local == "thead":
            for row in child.iter():
                row_local = _local(row.tag)
                if row_local == "row":
                    header_cells = _parse_cals_row(row)
                    break  # Only first header row

        elif child_local == "tbody":
            for row in child.iter():
                row_local = _local(row.tag)
                if row_local == "row":
                    body_rows.append(_parse_cals_row(row))

    if not header_cells and not body_rows:
        return None
    return header_cells, body_rows


def _parse_cals_row(row: ET.Element) -> List[str]:
    """Extract cell text from a CALS row."""
    cells = []
    for child in row:
        child_local = _local(child.tag)
        if child_local == "entry":
            cells.append(clean_text(get_element_text(child)))
    return cells


def extract_references(root: ET.Element) -> List[str]:
    """Extract bibliography references."""
    refs = []

    for bib_ref in root.iter(_ns("ce:bib-reference")):
        ref_text = _format_reference(bib_ref)
        if ref_text:
            refs.append(ref_text)

    return refs


def _format_reference(bib_ref: ET.Element) -> str:
    """Format a single bibliography reference."""
    label_elem = _find(bib_ref, "ce:label")
    label = clean_text(label_elem.text) if label_elem is not None and label_elem.text else ""

    # Try ce:other-ref with source-text first (often has complete formatted text)
    for other_ref in bib_ref.iter(_ns("ce:other-ref")):
        source_text = _find(other_ref, "ce:source-text")
        if source_text is not None:
            text = clean_text("".join(source_text.itertext()))
            if text:
                return text

    # Try structured sb:reference
    for sb_ref in bib_ref.iter(_ns("sb:reference")):
        return _format_structured_reference(sb_ref)

    # Fallback: try source-text directly under bib-reference
    for st in bib_ref.iter(_ns("ce:source-text")):
        text = clean_text("".join(st.itertext()))
        if text:
            return text

    # Last resort: use label
    if label:
        return label

    return ""


def _format_structured_reference(sb_ref: ET.Element) -> str:
    """Format a structured sb:reference into a citation string."""
    parts: List[str] = []

    # Authors
    authors = []
    for author in sb_ref.iter(_ns("sb:author")):
        given = _find(author, "ce:given-name")
        surname = _find(author, "ce:surname")
        given_t = clean_text(given.text) if given is not None and given.text else ""
        surname_t = clean_text(surname.text) if surname is not None and surname.text else ""
        if surname_t:
            authors.append(f"{surname_t}, {given_t}".rstrip(", "))

    # Editors
    for editor in sb_ref.iter(_ns("sb:editor")):
        given = _find(editor, "ce:given-name")
        surname = _find(editor, "ce:surname")
        given_t = clean_text(given.text) if given is not None and given.text else ""
        surname_t = clean_text(surname.text) if surname is not None and surname.text else ""
        if surname_t and not authors:
            authors.append(f"{surname_t}, {given_t} (Ed.)".rstrip(", "))

    if authors:
        parts.append(", ".join(authors))

    # Year
    for date in sb_ref.iter(_ns("sb:date")):
        year = date.text
        if not year:
            year = date.get("year", "")
        if year:
            parts.append(f"({clean_text(year)})")
            break

    # Title
    for title in sb_ref.iter(_ns("sb:title")):
        title_elem = _find(title, "sb:maintitle")
        if title_elem is not None:
            text = clean_text("".join(title_elem.itertext()))
            if text:
                parts.append(text)
                break
        else:
            text = clean_text("".join(title.itertext()))
            if text:
                parts.append(text)
                break

    # Journal/Source
    for series in sb_ref.iter(_ns("sb:series")):
        title = _find(series, "sb:title")
        if title is not None:
            maintitle = _find(title, "sb:maintitle")
            if maintitle is not None:
                text = clean_text("".join(maintitle.itertext()))
                if text:
                    parts.append(text)
            else:
                text = clean_text("".join(title.itertext()))
                if text:
                    parts.append(text)

    # Volume, pages
    volume_nr = ""
    for vol in sb_ref.iter(_ns("sb:volume-nr")):
        if vol.text:
            volume_nr = clean_text(vol.text)
            break
    first_page = ""
    last_page = ""
    for fp in sb_ref.iter(_ns("sb:first-page")):
        if fp.text:
            first_page = clean_text(fp.text)
            break
    for lp in sb_ref.iter(_ns("sb:last-page")):
        if lp.text:
            last_page = clean_text(lp.text)
            break

    if volume_nr:
        page_str = ""
        if first_page and last_page:
            page_str = f", {first_page}-{last_page}"
        elif first_page:
            page_str = f", {first_page}"
        parts.append(f"{volume_nr}{page_str}")

    # DOI
    for doi in sb_ref.iter(_ns("ce:doi")):
        if doi.text:
            parts.append(f"doi:{clean_text(doi.text)}")
            break

    return ". ".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Block-format helpers (content_list_v2.json output)
# ---------------------------------------------------------------------------

def _spans(text: str) -> list:
    """Split text containing $...$ inline math into TextSpan / InlineEquation dicts."""
    parts = re.split(r'(\$[^$]+\$)', text)
    result = []
    for p in parts:
        if not p:
            continue
        if p.startswith('$') and p.endswith('$') and len(p) > 2:
            result.append({"type": "equation_inline", "content": p[1:-1]})
        else:
            result.append({"type": "text", "content": p})
    return result or [{"type": "text", "content": ""}]


def _para_block(text: str) -> dict:
    return {"type": "paragraph", "content": {"paragraph_content": _spans(text)}, "bbox": [0, 0, 0, 0]}


def _title_block(text: str, level: int) -> dict:
    return {"type": "title", "content": {"title_content": _spans(text), "level": level}, "bbox": [0, 0, 0, 0]}


def _reference_list_block(refs: list[str]) -> dict:
    # Same shape as MinerU's content_list_v2 reference lists, so keep_references treats both routes alike.
    items = [{"item_type": "text", "item_content": _spans(ref)} for ref in refs]
    return {"type": "list", "content": {"list_type": "reference_list", "list_items": items}, "bbox": [0, 0, 0, 0]}


def _table_block(table: ET.Element) -> dict | None:
    """Convert a ce:table element to a TableBlock dict with HTML content."""
    label_elem = _find(table, "ce:label")
    label = clean_text(label_elem.text) if label_elem is not None and label_elem.text else ""

    caption_spans = []
    caption_text = " ".join(t for t in (clean_text(get_element_text(p))
                                        for p in _findall(table, "ce:caption/ce:simple-para")) if t)
    if caption_text:
        prefix = f"{label}: " if label else ""
        caption_spans = _spans(prefix + caption_text)

    html = None
    for child in table.iter():
        if _local(child.tag) == "tgroup":
            rows_data = _parse_cals_tgroup(child)
            if rows_data:
                header, body = rows_data
                rows_html = ""
                if header:
                    cells = "".join(f"<th>{html_escape(c, quote=False)}</th>" for c in header)
                    rows_html += f"<tr>{cells}</tr>"
                for row in body:
                    cells = "".join(f"<td>{html_escape(c, quote=False)}</td>" for c in row)
                    rows_html += f"<tr>{cells}</tr>"
                html = f"<table>{rows_html}</table>"
            break

    footnotes = []
    for fn in _findall(table, "ce:table-footnote"):
        fn_label = clean_text(get_element_text(_find(fn, "ce:label")))
        fn_text = " ".join(clean_text(get_element_text(p)) for p in _findall(fn, "ce:note-para"))
        footnotes.append(f"{fn_label} {fn_text}".strip())
    for para in _findall(table, "ce:legend/ce:simple-para"):
        footnotes.append(clean_text(get_element_text(para)))
    footnote_text = " ".join(f for f in footnotes if f)

    if not caption_spans and html is None:
        return None

    return {
        "type": "table",
        "content": {
            "table_caption": caption_spans,
            "table_footnote": _spans(footnote_text) if footnote_text else [],
            "html": html,
            "table_nest_level": 1,
        },
        "bbox": [0, 0, 0, 0],
    }


def _figure_block(figure: ET.Element) -> dict | None:
    """Convert a ce:figure element to an ImageBlock dict. No image files exist for XML publications, so the source
    path is left empty; the caption (all paragraphs) and legend are kept."""
    label_elem = _find(figure, "ce:label")
    label = clean_text(label_elem.text) if label_elem is not None and label_elem.text else ""

    caption_text = " ".join(t for t in (clean_text(get_element_text(p))
                                        for p in _findall(figure, "ce:caption/ce:simple-para")) if t)
    if not caption_text:
        return None
    prefix = f"{label}: " if label else ""

    footnotes = []
    for fn in _findall(figure, "ce:figure-footnote"):
        fn_label = clean_text(get_element_text(_find(fn, "ce:label")))
        fn_text = " ".join(clean_text(get_element_text(p)) for p in _findall(fn, "ce:note-para"))
        footnotes.append(f"{fn_label} {fn_text}".strip())
    for para in _findall(figure, "ce:legend/ce:simple-para"):
        footnotes.append(clean_text(get_element_text(para)))
    footnote_text = " ".join(f for f in footnotes if f)

    return {
        "type": "image",
        "content": {
            "image_source": {"path": ""},
            "image_caption": _spans(prefix + caption_text),
            "image_footnote": _spans(footnote_text) if footnote_text else [],
        },
        "bbox": [0, 0, 0, 0],
    }


def _section_to_blocks(section: ET.Element, level: int = 2) -> list:
    """Recursively convert a ce:section into a list of block dicts."""
    blocks = []
    label_elem = _find(section, "ce:label")
    title_elem = _find(section, "ce:section-title")
    label = clean_text(get_element_text(label_elem)) if label_elem is not None else ""
    title = clean_text(get_element_text(title_elem)) if title_elem is not None else ""
    if title:
        heading = f"{label} {title}".strip() if label else title
        blocks.append(_title_block(heading, level))

    for child in section:
        local = _local(child.tag)
        if local in ("para", "simple-para"):
            text = clean_text(get_element_text(child))
            if text:
                blocks.append(_para_block(text))
        elif local == "section":
            blocks.extend(_section_to_blocks(child, level=level + 1))
        elif local == "table":
            tb = _table_block(child)
            if tb:
                blocks.append(tb)
        elif local == "figure":
            fb = _figure_block(child)
            if fb:
                blocks.append(fb)
    return blocks


def parse_elsevier_xml_to_blocks(xml_path: str) -> list:
    """
    Parse an Elsevier full-text XML file and return a content_list_v2.json-compatible
    structure: a list of pages, each page being a list of block dicts.

    XML has no page concept so all blocks are placed in a single page.

    Parameters
    ----------
    xml_path : str - Path to the Elsevier XML file.

    Returns
    -------
    list[list[dict]] - Single-element list (one page) containing all content blocks.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()
    blocks = []

    title = extract_title(root)
    if title:
        blocks.append(_title_block(title, level=1))

    abstract = extract_abstract(root)
    if abstract:
        blocks.append(_title_block("Abstract", level=2))
        for para in abstract.split("\n\n"):
            if para.strip():
                blocks.append(_para_block(para.strip()))

    for elem in root.iter(_ns("ce:sections")):
        for child in elem:
            local = _local(child.tag)
            if local == "section":
                blocks.extend(_section_to_blocks(child, level=2))
        break  # only first ce:sections block

    # Tables and figures from ce:floats that were not inline in a section
    for float_block in root.iter(_ns("ce:floats")):
        for child in float_block:
            local = _local(child.tag)
            if local == "table":
                tb = _table_block(child)
                if tb:
                    blocks.append(tb)
            elif local == "figure":
                fb = _figure_block(child)
                if fb:
                    blocks.append(fb)

    refs = extract_references(root)
    if refs:
        blocks.append(_title_block("References", level=2))
        blocks.append(_reference_list_block(refs))

    return [blocks]


def _xml_to_json_file(xml_path: str, out_path: str) -> str:
    """
    Parses one XML file and writes its content list JSON. Module-level and string-only so it can run in a worker
    process; it must not touch the active corpus (get_corpus() is not set in child processes).
    """
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(parse_elsevier_xml_to_blocks(xml_path), ensure_ascii=False), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Converter class
# ---------------------------------------------------------------------------

class ElsevierXmlTransformer(Transformer):
    """
    Converts Elsevier full-text XML publications to content_list_v2.json format.
    Inherits iteration, caching, and error handling from Converter. With max_workers > 1, files are parsed in a
    process pool; results and cache writes are handled in the parent process.
    """
    # Parses one file to JSON; subclasses for other XML formats swap this out.
    _worker = staticmethod(_xml_to_json_file)

    def __init__(self, publication_list: List[Publication], max_workers: int | None = None):
        super().__init__(publication_list)
        self.max_workers = max_workers or max(1, (os.cpu_count() or 2) - 1)

    def transform_all(self) -> None:
        if self.max_workers <= 1:
            return super().transform_all()

        total = len(self.publication_list)
        pending = [p for p in self.publication_list if p.content_json_filepath is None]
        passed, failed = total - len(pending), 0
        logging.info(f"{self.__class__.__name__} starting transformation of {total} publication(s) "
                     f"with {self.max_workers} worker processes.")

        with ProcessPoolExecutor(max_workers=self.max_workers) as pool, \
                tqdm(total=total, initial=passed, desc=self.__class__.__name__, unit="pub",
                     leave=True, dynamic_ncols=True) as bar:
            futures = {
                pool.submit(self._worker, str(p.publication_filepath), str(self._build_output_path(p))): p
                for p in pending
            }
            for future in as_completed(futures):
                pub = futures[future]
                try:
                    pub.content_json_filepath = Path(future.result())
                    self._cache_result(pub)
                    passed += 1
                except Exception as e:
                    logging.warning(f"Transformation failed for {pub.doi}: {e} — skipping.")
                    failed += 1
                bar.update(1)
                bar.set_postfix_str(progress_split_bar(passed, failed, total))

        logging.info(f"{self.__class__.__name__} finished — {passed} succeeded, {failed} failed.")

    def transform2json(self, pub: Publication) -> Path | None:
        """
        Parses a single Elsevier XML file and writes a content_list_v2.json to
        <corpus>/intermediates/<stem>/auto/<stem>_content_list_v2.json.

        Parameters
        ----------
        pub : Publication - Must have publication_filepath pointing to an .xml file.

        Returns
        -------
        Path to the written JSON file, or None if conversion failed.
        """
        output_path = Path(self._worker(str(pub.publication_filepath), str(self._build_output_path(pub))))
        logging.debug(f"{self.__class__.__name__} converted {pub.doi} → {output_path}")
        return output_path


