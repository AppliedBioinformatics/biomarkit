"""
Parse PMC BioC XML articles (https://www.ncbi.nlm.nih.gov/research/bionlp/APIs/BioC-PMC/) into content_list_v2.json
block format. BioC is a flat list of passages, each tagged with a "type" infon (front, title_N, paragraph, table, ref, ...)
and a "section_type" infon (INTRO, METHODS, TABLE, FIG, REF, ...). Table and figure parts share an "id" infon.

BioC drops formulas from the passage text, so no equation blocks are produced. Footnote passages and published peer-review
history (REVIEW_INFO) are written as page_footnote / page_aside_text blocks, so keep_boilerplate controls them.
"""

import json
import re
import xml.etree.ElementTree as ET
from html import escape as html_escape
from pathlib import Path

from biomarkit.text_transformation.converters.elsevier2json import ElsevierXmlTransformer

_TITLE_RE = re.compile(r"^title_(\d+)$")


def _text_spans(text: str) -> list:
    # Plain text only - unlike elsevier2json._spans, "$" is not treated as inline math (BioC carries no LaTeX).
    return [{"type": "text", "content": text}]


def _para_block(text: str) -> dict:
    return {"type": "paragraph", "content": {"paragraph_content": _text_spans(text)}, "bbox": [0, 0, 0, 0]}


def _title_block(text: str, level: int) -> dict:
    return {"type": "title", "content": {"title_content": _text_spans(text), "level": level}, "bbox": [0, 0, 0, 0]}


def _footnote_block(text: str) -> dict:
    return {"type": "page_footnote", "content": {"page_footnote_content": _text_spans(text)}, "bbox": [0, 0, 0, 0]}


def _aside_block(text: str) -> dict:
    return {"type": "page_aside_text", "content": {"page_aside_text_content": _text_spans(text)}, "bbox": [0, 0, 0, 0]}


def _reference_list_block(refs: list[str]) -> dict:
    # Same shape as MinerU's content_list_v2 reference lists, so keep_references treats both routes alike.
    items = [{"item_type": "text", "item_content": _text_spans(ref)} for ref in refs]
    return {"type": "list", "content": {"list_type": "reference_list", "list_items": items}, "bbox": [0, 0, 0, 0]}


def _clean(text: str | None) -> str:
    return " ".join((text or "").split())


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _infons(passage: ET.Element) -> dict:
    return {i.get("key"): i.text or "" for i in passage.findall("infon")}


def _format_reference(infons: dict, title: str) -> str:
    """Builds 'Surname AB, Surname C. Title. Source Year;Volume:fpage-lpage.' from a ref passage's infons."""
    authors = []
    for key in sorted((k for k in infons if k.startswith("name_")), key=lambda k: int(k.split("_")[1])):
        fields = dict(part.split(":", 1) for part in infons[key].split(";") if ":" in part)
        surname = fields.get("surname", "")
        initials = "".join(g[0] for g in fields.get("given-names", "").split() if g)
        authors.append(f"{surname} {initials}".strip() or infons[key])

    citation = " ".join(x for x in (infons.get("source"), infons.get("year")) if x)
    if infons.get("volume"):
        citation += f";{infons['volume']}"
    pages = "-".join(x for x in (infons.get("fpage"), infons.get("lpage")) if x)
    if pages:
        citation += f":{pages}"

    return ". ".join(x for x in (", ".join(authors), title.rstrip("."), citation.strip(";: ")) if x)


def _table_html(xml_str: str) -> str | None:
    """Rebuilds the JATS <table> in a table passage's "xml" infon as plain <table><tr><th|td> HTML."""
    try:
        table = ET.fromstring(xml_str.encode("utf-8"))
    except ET.ParseError:
        return None

    header_rows = {id(tr) for el in table.iter() if _local(el.tag) == "thead"
                   for tr in el.iter() if _local(tr.tag) == "tr"}
    rows_html = ""
    for tr in table.iter():
        if _local(tr.tag) != "tr":
            continue
        cell_tag = "th" if id(tr) in header_rows else "td"
        cells = [_clean("".join(c.itertext())) for c in tr if _local(c.tag) in ("td", "th")]
        rows_html += "<tr>" + "".join(f"<{cell_tag}>{html_escape(c, quote=False)}</{cell_tag}>" for c in cells) + "</tr>"

    return f"<table>{rows_html}</table>" if rows_html else None


def _float_block(fl: dict) -> dict | None:
    """Turns a grouped table/figure (captions, html, footnotes) into a table or image block dict."""
    caption = " ".join(fl["caption"])
    footnote = " ".join(fl["footnote"])

    if fl["kind"] == "table":
        if not caption and fl["html"] is None:
            return None
        return {
            "type": "table",
            "content": {
                "table_caption": _text_spans(caption) if caption else [],
                "table_footnote": _text_spans(footnote) if footnote else [],
                "html": fl["html"],
                "table_nest_level": 1,
            },
            "bbox": [0, 0, 0, 0],
        }

    if not caption:
        return None
    # No image files exist for XML publications, so the source path is left empty; the caption is kept.
    return {
        "type": "image",
        "content": {
            "image_source": {"path": ""},
            "image_caption": _text_spans(caption),
            "image_footnote": _text_spans(footnote) if footnote else [],
        },
        "bbox": [0, 0, 0, 0],
    }


def parse_bioc_xml_to_blocks(xml_path: str) -> list:
    """
    Parse a BioC XML file and return a content_list_v2.json-compatible structure: a single page holding all blocks.

    Tables and figures are grouped by their "id" infon and placed where their first passage appears. References are
    collected into a trailing "References" section, replacing BioC's own REF heading.

    Parameters
    ----------
    xml_path : str - Path to the BioC XML file.

    Returns
    -------
    list[list[dict]] - Single-element list (one page) containing all content blocks.
    """
    document = ET.parse(xml_path).getroot().find("document")
    blocks, refs, floats = [], [], {}
    abstract_started = False

    for passage in document.findall("passage"):
        infons = _infons(passage)
        ptype, section = infons.get("type", ""), infons.get("section_type", "")
        text = _clean(passage.findtext("text"))

        if ptype == "ref":
            ref = _format_reference(infons, text)
            if ref:
                refs.append(ref)
            continue

        if section in ("TABLE", "FIG"):
            kind = "table" if section == "TABLE" else "figure"
            key = (kind, infons.get("id") or f"{kind}_{len(floats)}")
            if key not in floats:
                floats[key] = {"kind": kind, "caption": [], "html": None, "footnote": []}
                blocks.append(key)  # placeholder, replaced once all parts are collected
            fl = floats[key]
            if ptype == "table":
                fl["html"] = _table_html(infons["xml"]) if infons.get("xml") else None
            elif ptype.endswith("caption"):
                if text:
                    fl["caption"].append(text)
            elif text:
                fl["footnote"].append(text)
            continue

        if section == "REF" or not text:
            continue

        # Journal boilerplate, removed by keep_boilerplate=False like MinerU's page-level blocks.
        if ptype == "footnote":
            blocks.append(_footnote_block(text))
            continue
        if section == "REVIEW_INFO":
            blocks.append(_aside_block(text))
            continue

        if ptype == "front":
            blocks.append(_title_block(text, 1))
        elif section == "ABSTRACT":
            if not abstract_started:
                blocks.append(_title_block("Abstract", 2))
                abstract_started = True
            if "title" in ptype:
                blocks.append(_title_block(text, 3))
            else:
                blocks.append(_para_block(text))
        elif match := _TITLE_RE.match(ptype):
            blocks.append(_title_block(text, int(match.group(1)) + 1))
        elif "title" in ptype:
            blocks.append(_title_block(text, 2))
        else:
            blocks.append(_para_block(text))

    blocks = [_float_block(floats[b]) if isinstance(b, tuple) else b for b in blocks]
    blocks = [b for b in blocks if b is not None]

    if refs:
        blocks.append(_title_block("References", 2))
        blocks.append(_reference_list_block(refs))

    return [blocks]


def _bioc_to_json_file(xml_path: str, out_path: str) -> str:
    """Worker-process entry point; see elsevier2json._xml_to_json_file."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(parse_bioc_xml_to_blocks(xml_path), ensure_ascii=False), encoding="utf-8")
    return out_path


class BioCXmlTransformer(ElsevierXmlTransformer):
    """
    Converts PMC BioC XML publications to content_list_v2.json format. Reuses ElsevierXmlTransformer's sequential and
    process-pool iteration with the BioC parser swapped in.
    """
    _worker = staticmethod(_bioc_to_json_file)
