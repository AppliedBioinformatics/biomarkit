"""
Parse Elsevier full-text XML articles into standardised markdown format.
Provides both standalone parsing functions and the ElsevierXmlConverter class
for use within the text-transformation pipeline.

Features:
- Extracts title, authors, abstract, keywords, body text, and references
- Converts LaTeX/MathML formulas to markdown format
- Parses CALS tables into markdown table format
- Organizes orphaned figures and tables under explicit "# Figures" and "# Tables" headers
- Handles inline markup (bold, italic, superscript, subscript)
- Preserves document structure with proper heading levels
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

from text_download.basemodels.publication import Publication
from text_transformation.converters.ABC.transformer import Transformer


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


def _ns(tag: str) -> str:
    """Expand a namespace-prefixed tag like 'ce:para' to '{uri}para'."""
    if ":" in tag:
        prefix, local = tag.split(":", 1)
        uri = NS.get(prefix, "")
        return f"{{{uri}}}{local}"
    return tag


def _find(elem: ET.Element, path: str) -> Optional[ET.Element]:
    """Find element using colon-prefixed namespace path."""
    parts = path.split("/")
    expanded = "/".join(_ns(p) if p != "." and p != ".." else p for p in parts)
    return elem.find(expanded)


def _findall(elem: ET.Element, path: str) -> List[ET.Element]:
    """Find all elements using colon-prefixed namespace path."""
    parts = path.split("/")
    expanded = "/".join(_ns(p) if p != "." and p != ".." else p for p in parts)
    return elem.findall(expanded)


def clean_text(text: str) -> str:
    """Normalise whitespace in text."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def get_element_text(elem: ET.Element) -> str:
    """Recursively extract and format text from an element, handling inline markup."""
    if elem is None:
        return ""

    tag = elem.tag
    # Strip namespace for comparison
    local = tag.rsplit("}", 1)[-1] if "}" in tag else tag

    parts: List[str] = []

    # Add element's own text
    if elem.text:
        parts.append(elem.text)

    # Process children
    for child in elem:
        child_text = get_element_text(child)
        child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag

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
    local = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag

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
        latex_operators = {
            "∑": r"\sum",
            "∏": r"\prod",
            "∫": r"\int",
            "≈": r"\approx",
            "≠": r"\neq",
            "≤": r"\leq",
            "≥": r"\geq",
            "±": r"\pm",
            "∞": r"\infty",
            "α": r"\alpha",
            "β": r"\beta",
            "γ": r"\gamma",
            "δ": r"\delta",
            "ε": r"\epsilon",
            "θ": r"\theta",
            "λ": r"\lambda",
            "μ": r"\mu",
            "π": r"\pi",
            "ρ": r"\rho",
            "σ": r"\sigma",
            "τ": r"\tau",
            "φ": r"\phi",
            "χ": r"\chi",
            "ω": r"\omega"
        }

        for symbol, latex in latex_operators.items():
            combined = combined.replace(symbol, latex)

        return combined

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
            if child.tag.rsplit("}", 1)[-1] == "mtr":
                row_cells = []
                for cell in child:
                    if cell.tag.rsplit("}", 1)[-1] == "mtd":
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
        local = descendant.tag.rsplit("}", 1)[-1] if "}" in descendant.tag else descendant.tag
        if local == "math":
            math = descendant
            break

    if math is not None:
        latex_content = _parse_mathml(math)
        # Determine if this is a display (block) or inline formula
        parent_tag = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag

        if parent_tag == "display":
            # Display formula (centered, block-level)
            return f"$$\n{latex_content}\n$$"
        else:
            # Inline formula
            return f"${latex_content}$"

    # Fallback to text content with basic LaTeX formatting for common patterns
    text_content = clean_text("".join(elem.itertext()))

    # Apply basic LaTeX formatting to common mathematical expressions
    text_content = _enhance_text_formulas(text_content)

    return text_content


def _enhance_text_formulas(text: str) -> str:
    """Apply basic LaTeX formatting to common mathematical expressions in plain text."""
    if not text:
        return text

    # Common mathematical expression patterns
    import re

    # Pattern for subscripts like n_i, p_i, etc.
    text = re.sub(r'(\w+)_(\w+)', r'$\1_{\2}$', text)

    # Pattern for superscripts like x^2, R^2, etc.
    text = re.sub(r'(\w+)\^(\w+)', r'$\1^{\2}$', text)

    # Greek letters and mathematical symbols
    greek_symbols = {
        'alpha': r'\alpha', 'beta': r'\beta', 'gamma': r'\gamma', 'delta': r'\delta',
        'epsilon': r'\epsilon', 'theta': r'\theta', 'lambda': r'\lambda', 'mu': r'\mu',
        'pi': r'\pi', 'rho': r'\rho', 'sigma': r'\sigma', 'tau': r'\tau',
        'phi': r'\phi', 'chi': r'\chi', 'omega': r'\omega'
    }

    for word, latex in greek_symbols.items():
        # Escape the LaTeX command for use in replacement string
        latex_escaped = latex.replace('\\', r'\\')
        text = re.sub(rf'\b{word}\b', f'${latex_escaped}$', text, flags=re.IGNORECASE)

    # Mathematical operators and symbols
    operators = {
        '±': r'$\pm$', '∑': r'$\sum$', '∏': r'$\prod$', '∫': r'$\int$',
        '≈': r'$\approx$', '≠': r'$\neq$', '≤': r'$\leq$', '≥': r'$\geq$',
        '∞': r'$\infty$', 'Σ': r'$\Sigma$', 'Π': r'$\Pi$', '⌊': r'$\lfloor$',
        '⌋': r'$\rfloor$', '⌈': r'$\lceil$', '⌉': r'$\rceil$', '∂': r'$\partial$',
        '∇': r'$\nabla$', '∀': r'$\forall$', '∃': r'$\exists$', '∈': r'$\in$',
        '∉': r'$\notin$', '⊂': r'$\subset$', '⊃': r'$\supset$', '⊆': r'$\subseteq$',
        '⊇': r'$\supseteq$', '∩': r'$\cap$', '∪': r'$\cup$', '×': r'$\times$',
        '÷': r'$\div$', '√': r'$\sqrt{}$', '∴': r'$\therefore$', '∵': r'$\because$'
    }

    for symbol, latex in operators.items():
        text = text.replace(symbol, latex)

    # Formulas like "S = 1 - Σ[...]" - convert to display format
    if re.search(r'[A-Z]\s*=.*[∑∏∫Σ]', text):
        # This looks like a mathematical formula definition
        text = f"$${text}$$"
    elif 'formula:' in text.lower() and any(op in text for op in ['=', '∑', 'Σ', '∏', '∫']):
        # Mathematical expressions following "formula:"
        parts = text.split(':', 1)
        if len(parts) == 2:
            prefix, formula = parts
            text = f"{prefix}: $${formula.strip()}$$"

    return text


def extract_title(root: ET.Element) -> str:
    """Extract article title."""
    # Try from article head first (more accurate)
    for article in root.iter(_ns("ja:article")):
        head = article.find(_ns("ja:head"))
        if head is None:
            # head might be unnamespaced inside article
            for child in article:
                child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
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
            child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            if child_local in ("simple-head", "head"):
                title_elem = _find(child, "ce:title")
                if title_elem is not None:
                    return clean_text(get_element_text(title_elem))

    # Fallback: look in any head element
    for head in root.iter():
        local = head.tag.rsplit("}", 1)[-1] if "}" in head.tag else head.tag
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
        local = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        if local == "coredata":
            for child in elem:
                child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
                if child_local == "title":
                    return clean_text(child.text or "")
    return ""


def extract_authors(root: ET.Element) -> List[str]:
    """Extract author names from the article head."""
    authors = []

    # Find ce:author-group in article head
    for author_group in root.iter(_ns("ce:author-group")):
        for author in _findall(author_group, "ce:author"):
            given = _find(author, "ce:given-name")
            surname = _find(author, "ce:surname")
            given_text = clean_text(given.text) if given is not None and given.text else ""
            surname_text = clean_text(surname.text) if surname is not None and surname.text else ""
            if surname_text:
                name = f"{given_text} {surname_text}".strip()
                authors.append(name)

    if authors:
        return authors

    # Fallback: dc:creator from coredata
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        if local == "creator" and elem.text:
            authors.append(clean_text(elem.text))

    return authors


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
        local = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        if local == "description" and elem.text:
            return clean_text(elem.text)

    return ""


def extract_keywords(root: ET.Element) -> List[str]:
    """Extract keywords."""
    keywords = []

    # From ce:keywords in article head
    for kw_group in root.iter(_ns("ce:keywords")):
        cls = kw_group.get("class", "")
        if cls == "keyword" or not cls:
            for kw in _findall(kw_group, "ce:keyword"):
                text_elem = _find(kw, "ce:text")
                if text_elem is not None and text_elem.text:
                    keywords.append(clean_text(text_elem.text))

    if keywords:
        return keywords

    # Fallback: dcterms:subject
    for elem in root.iter():
        local = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        if local == "subject" and elem.text:
            keywords.append(clean_text(elem.text))

    return keywords


def parse_section(section: ET.Element, level: int = 2, collect_floats: Optional[List[tuple[str, str]]] = None) -> str:
    """Recursively parse a ce:section into markdown.

    Args:
        section: The XML section element to parse
        level: Heading level (default 2)
        collect_floats: Optional list to collect (content, type) tuples for figures/tables
    """
    parts: List[str] = []

    # Get label and title
    label_elem = _find(section, "ce:label")
    title_elem = _find(section, "ce:section-title")

    label = clean_text(get_element_text(label_elem)) if label_elem is not None else ""
    title = clean_text(get_element_text(title_elem)) if title_elem is not None else ""

    if title:
        heading_prefix = "#" * min(level, 6)
        if label:
            parts.append(f"{heading_prefix} {label} {title}")
        else:
            parts.append(f"{heading_prefix} {title}")

    # Process paragraphs and child sections in document order
    for child in section:
        child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag

        if child_local == "para" or child_local == "simple-para":
            text = clean_text(get_element_text(child))
            if text:
                parts.append(text)

        elif child_local == "section":
            sub = parse_section(child, level=level + 1, collect_floats=collect_floats)
            if sub:
                parts.append(sub)

        elif child_local == "figure":
            fig_text = parse_figure(child)
            if fig_text:
                parts.append(fig_text)
                # Collect for potential reorganization
                if collect_floats is not None:
                    collect_floats.append((fig_text, "figure"))

        elif child_local == "table":
            table_text = parse_table(child)
            if table_text:
                if collect_floats is not None:
                    # Defer to Tables section rather than embedding inline
                    collect_floats.append((table_text, "table"))
                else:
                    parts.append(table_text)

    return "\n\n".join(parts)


def parse_figure(fig: ET.Element) -> str:
    """Parse a ce:figure element into a markdown reference."""
    label_elem = _find(fig, "ce:label")
    label = clean_text(label_elem.text) if label_elem is not None and label_elem.text else ""

    caption_text = ""
    caption = _find(fig, "ce:caption")
    if caption is not None:
        for para in caption.iter(_ns("ce:simple-para")):
            caption_text = clean_text(get_element_text(para))
            break

    if label and caption_text:
        return f"[{label}: {caption_text}]"
    elif label:
        return f"[{label}]"
    return ""


def parse_table(table: ET.Element) -> str:
    """Parse a ce:table element into markdown table format."""
    parts: List[str] = []

    # Table label and caption
    label_elem = _find(table, "ce:label")
    label = clean_text(label_elem.text) if label_elem is not None and label_elem.text else ""

    caption_text = ""
    caption = _find(table, "ce:caption")
    if caption is not None:
        for para in caption.iter(_ns("ce:simple-para")):
            caption_text = clean_text(get_element_text(para))
            break

    if label:
        parts.append(f"**{label}**" + (f": {caption_text}" if caption_text else ""))

    # Parse CALS table structure
    tgroup = None
    for child in table.iter():
        child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
        if child_local == "tgroup":
            tgroup = child
            break

    if tgroup is not None:
        rows_data = _parse_cals_tgroup(tgroup)
        if rows_data:
            header, body = rows_data
            if header:
                # Calculate maximum column count across all rows
                max_cols = len(header)
                for row in body:
                    max_cols = max(max_cols, len(row))

                # Extend header if data rows have more columns
                while len(header) < max_cols:
                    header.append(f"Col {len(header) + 1}")

                # Add blank line before table for proper markdown separation
                parts.append("")

                # Generate table header
                parts.append("| " + " | ".join(header) + " |")
                parts.append("| " + " | ".join("---" for _ in header) + " |")

                # Generate table rows with normalized column count
                for row in body:
                    # Pad row to match header length
                    while len(row) < max_cols:
                        row.append("")
                    # Truncate if somehow longer (safety)
                    row = row[:max_cols]
                    parts.append("| " + " | ".join(row) + " |")

                # Add blank line after table for proper markdown separation
                parts.append("")

    # Table footnotes
    for footnote in table.iter(_ns("ce:table-footnote")):
        fn_label = ""
        fn_text = ""
        fl = _find(footnote, "ce:label")
        if fl is not None and fl.text:
            fn_label = fl.text.strip()
        for np in footnote.iter(_ns("ce:note-para")):
            fn_text = clean_text(get_element_text(np))
            break
        if fn_label and fn_text:
            parts.append(f"^{fn_label}^ {fn_text}")
        elif fn_text:
            parts.append(fn_text)

    return "\n".join(parts) if parts else ""


def _parse_cals_tgroup(tgroup: ET.Element):
    """Parse CALS tgroup into header and body rows."""
    header_cells: List[str] = []
    body_rows: List[List[str]] = []

    for child in tgroup.iter():
        child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag

        if child_local == "thead":
            for row in child.iter():
                row_local = row.tag.rsplit("}", 1)[-1] if "}" in row.tag else row.tag
                if row_local == "row":
                    header_cells = _parse_cals_row(row)
                    break  # Only first header row

        elif child_local == "tbody":
            for row in child.iter():
                row_local = row.tag.rsplit("}", 1)[-1] if "}" in row.tag else row.tag
                if row_local == "row":
                    body_rows.append(_parse_cals_row(row))

    if not header_cells and not body_rows:
        return None
    return header_cells, body_rows


def _parse_cals_row(row: ET.Element) -> List[str]:
    """Extract cell text from a CALS row."""
    cells = []
    for child in row:
        child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
        if child_local == "entry":
            cell_text = clean_text(get_element_text(child))
            # Escape pipe characters in cell content
            cell_text = cell_text.replace("|", "\\|")
            cells.append(cell_text)
    return cells


def parse_body_sections(root: ET.Element, collect_floats: Optional[List[tuple[str, str]]] = None) -> str:
    """Find and parse all body sections.

    Args:
        root: Root XML element
        collect_floats: Optional list to collect (content, type) tuples for figures/tables
    """
    parts: List[str] = []

    # Find ce:sections within body
    for elem in root.iter(_ns("ce:sections")):
        for child in elem:
            child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            if child_local == "section":
                section_md = parse_section(child, level=2, collect_floats=collect_floats)
                if section_md:
                    parts.append(section_md)
        break  # Only process first ce:sections block

    return "\n\n".join(parts)


def extract_floats(root: ET.Element) -> Dict[str, tuple[str, str]]:
    """Extract figures and tables from ce:floats for reference.

    Returns:
        Dict mapping element IDs to (content, type) tuples where type is 'figure' or 'table'.
    """
    floats = {}
    for float_block in root.iter(_ns("ce:floats")):
        for child in float_block:
            child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            elem_id = child.get("id", "")
            if child_local == "figure":
                content = parse_figure(child)
                if content:
                    floats[elem_id] = (content, "figure")
            elif child_local == "table":
                content = parse_table(child)
                if content:
                    floats[elem_id] = (content, "table")
    return floats


def extract_acknowledgments(root: ET.Element) -> str:
    """Extract acknowledgments section."""
    for ack in root.iter(_ns("ce:acknowledgment")):
        paras = []
        for child in ack:
            child_local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            if child_local == "para" or child_local == "simple-para":
                text = clean_text(get_element_text(child))
                if text:
                    paras.append(text)
        if paras:
            return "\n\n".join(paras)
    return ""


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


def parse_elsevier_xml(xml_path: str, organize_floats: bool = True) -> str:
    """
    Parse an Elsevier full-text XML file and return standardised markdown.

    Parameters
    ----------
    xml_path : str - Path to the Elsevier XML file.
    organize_floats : bool - If True, add explicit #Tables and #Figures headers for orphaned floats.

    Returns
    -------
    str - Markdown formatted string of the article.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    md_parts: List[str] = []

    # Title
    title = extract_title(root)
    if title:
        md_parts.append(f"# {title}")

    # Authors
    authors = extract_authors(root)
    if authors:
        md_parts.append(", ".join(authors))

    # Abstract
    abstract = extract_abstract(root)
    if abstract:
        md_parts.append(f"## Abstract\n\n{abstract}")

    # Keywords
    keywords = extract_keywords(root)
    if keywords:
        md_parts.append(f"**Keywords:** {', '.join(keywords)}")

    # Collect floats (figures/tables defined in ce:floats)
    floats = extract_floats(root)

    # Collect all figures and tables during body parsing
    inline_floats: List[tuple[str, str]] = []

    # Body sections
    body = parse_body_sections(root, collect_floats=inline_floats)
    if body:
        md_parts.append(body)

    # Separate inline floats by type
    all_figures = [md for md, t in inline_floats if t == "figure"]
    all_tables = [md for md, t in inline_floats if t == "table"]

    # Add any orphaned floats from ce:floats not already captured
    for float_id, (float_md, float_type) in floats.items():
        if float_md and float_md not in body:
            if float_type == "figure" and float_md not in all_figures:
                all_figures.append(float_md)
            elif float_type == "table" and float_md not in all_tables:
                all_tables.append(float_md)

    # Write figures and tables under explicit section headers
    if organize_floats:
        if all_figures:
            md_parts.append("# Figures")
            md_parts.extend(all_figures)
        if all_tables:
            md_parts.append("# Tables")
            md_parts.extend(all_tables)
    else:
        md_parts.extend(all_figures)
        md_parts.extend(all_tables)

    # Acknowledgments
    ack = extract_acknowledgments(root)
    if ack:
        md_parts.append(f"## Acknowledgments\n\n{ack}")

    # References
    refs = extract_references(root)
    if refs:
        ref_lines = ["## References", ""]
        for ref in refs:
            ref_lines.append(f"* {ref}")
        md_parts.append("\n".join(ref_lines))

    return "\n\n".join(md_parts) + "\n"


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


def _table_block(table: ET.Element) -> dict | None:
    """Convert a ce:table element to a TableBlock dict with HTML content."""
    label_elem = _find(table, "ce:label")
    label = clean_text(label_elem.text) if label_elem is not None and label_elem.text else ""

    caption_spans = []
    caption = _find(table, "ce:caption")
    if caption is not None:
        for para in caption.iter(_ns("ce:simple-para")):
            caption_text = clean_text(get_element_text(para))
            if caption_text:
                prefix = f"{label}: " if label else ""
                caption_spans = _spans(prefix + caption_text)
                break

    html = None
    for child in table.iter():
        if child.tag.rsplit("}", 1)[-1] == "tgroup":
            rows_data = _parse_cals_tgroup(child)
            if rows_data:
                header, body = rows_data
                rows_html = ""
                if header:
                    cells = "".join(f"<th>{c}</th>" for c in header)
                    rows_html += f"<tr>{cells}</tr>"
                for row in body:
                    cells = "".join(f"<td>{c}</td>" for c in row)
                    rows_html += f"<tr>{cells}</tr>"
                html = f"<table>{rows_html}</table>"
            break

    if not caption_spans and html is None:
        return None

    return {
        "type": "table",
        "content": {
            "table_caption": caption_spans,
            "table_footnote": [],
            "html": html,
            "table_nest_level": 1,
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
        local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
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
        # figures skipped — no image files exist for XML publications
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
            local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            if local == "section":
                blocks.extend(_section_to_blocks(child, level=2))
        break  # only first ce:sections block

    # Tables from ce:floats that were not inline in a section
    for float_block in root.iter(_ns("ce:floats")):
        for child in float_block:
            local = child.tag.rsplit("}", 1)[-1] if "}" in child.tag else child.tag
            if local == "table":
                tb = _table_block(child)
                if tb:
                    blocks.append(tb)

    refs = extract_references(root)
    if refs:
        blocks.append(_title_block("References", level=2))
        for ref in refs:
            blocks.append(_para_block(ref))

    return [blocks]


# ---------------------------------------------------------------------------
# Converter class
# ---------------------------------------------------------------------------

class ElsevierXmlTransformer(Transformer):
    """
    Converts Elsevier full-text XML publications to content_list_v2.json format.
    Inherits iteration, caching, and error handling from Converter.
    """

    def transform2json(self, pub: Publication) -> Path | None:
        """
        Parses a single Elsevier XML file and writes a content_list_v2.json to
        RAW_MARKDOWN_DIR/<stem>/auto/<stem>_content_list_v2.json.

        Parameters
        ----------
        pub : Publication - Must have publication_filepath pointing to an .xml file.

        Returns
        -------
        Path to the written JSON file, or None if conversion failed.
        """
        output_path = self._build_output_path(pub)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        blocks = parse_elsevier_xml_to_blocks(str(pub.publication_filepath))
        output_path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")

        logging.info(f"Elsevier XML converted for {pub.doi} → {output_path}")
        return output_path


if __name__ == "__main__":
    # Testing block - convert XML files to markdown and save to TMP
    # Note: This will only work if run from the project directory due to imports
    import sys
    sys.path.append(str(Path(__file__).parent.parent.parent))
    from config import TMP_DIR, DOWNLOAD_DIR

    TMP_DIR.mkdir(exist_ok=True)

    # Find and process XML files
    xml_files = []
    for xml_dir in [DOWNLOAD_DIR]:
        if xml_dir.exists():
            xml_files.extend(xml_dir.glob("elsevier_*.xml"))

    for xml_file in xml_files[:5]:
        try:
            markdown_content = parse_elsevier_xml(str(xml_file))
            output_file = TMP_DIR / f"{xml_file.stem}.md"
            output_file.write_text(markdown_content, encoding="utf-8")
        except (ET.ParseError, FileNotFoundError, UnicodeError):
            continue
