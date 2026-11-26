# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "pymupdf"]
# ///
"""
Build the full-paper ground truth (GT) from PMC BioC XML and check each XML/PDF pair.

    uv run evals/fullpaper_benchmark/build_gt.py

Each BioC passage keeps NCBI's section_type; core text = INTRO/METHODS/RESULTS/DISCUSS/CONCL headings and paragraphs.
Figures and tables are single units (caption + footnote, plus HTML for tables).
A paper is excluded if it lacks INTRO plus one of METHODS/RESULTS/DISCUSS or has < MIN_CORE_PARAGRAPHS core paragraphs,
or if < MIN_VERSION_MATCH of its core paragraphs are found in the PDF text layer (author manuscript vs version of record).
The first TARGET passing papers per publisher are selected. Writes gt/<id>.json, gt/<id>.md and updates manifest.csv.
"""
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from html import escape
from pathlib import Path

import pandas as pd
import pymupdf

ROOT = Path(__file__).parent
GT = ROOT / "gt"
CORE_SECTIONS = {"INTRO", "METHODS", "RESULTS", "DISCUSS", "CONCL"}
TARGET = {"wiley": 20, "elsevier": 10, "springer": 10, "frontiers": 10, "mdpi": 10, "plos": 10}
MIN_CORE_PARAGRAPHS = 10
MIN_VERSION_MATCH = 0.90  # share of core paragraphs found in the PDF
PARA_FOUND = 0.80         # share of a paragraph's word 5-grams present in the PDF


def clean(text):
    return " ".join((text or "").split())


def table_html(xml_str):
    """JATS <table> -> HTML, keeping colspan/rowspan for TEDS."""
    try:
        table = ET.fromstring(xml_str.encode("utf-8"))
    except ET.ParseError:
        return None
    local = lambda el: el.tag.rsplit("}", 1)[-1]
    head = {id(tr) for el in table.iter() if local(el) == "thead" for tr in el.iter() if local(tr) == "tr"}
    rows = ""
    for tr in (el for el in table.iter() if local(el) == "tr"):
        tag = "th" if id(tr) in head else "td"
        rows += "<tr>"
        for c in (c for c in tr if local(c) in ("td", "th")):
            span = "".join(f' {a}="{c.get(a)}"' for a in ("colspan", "rowspan") if c.get(a) not in (None, "1"))
            rows += f"<{tag}{span}>{escape(clean(''.join(c.itertext())), quote=False)}</{tag}>"
        rows += "</tr>"
    return f"<table>{rows}</table>" if rows else None


def parse_bioc(path):
    doc = ET.parse(path).getroot().find("document")
    meta, blocks, floats = {}, [], {}
    for p in doc.findall("passage"):
        inf = {i.get("key"): i.text or "" for i in p.findall("infon")}
        ptype, section, text = inf.get("type", ""), inf.get("section_type", ""), clean(p.findtext("text"))
        if ptype == "front":
            meta = {"pmcid": "PMC" + inf.get("article-id_pmc", "").removeprefix("PMC"), "doi": inf.get("article-id_doi"),
                    "year": inf.get("year"), "license": inf.get("license")}
            blocks.append({"kind": "title", "section_type": section, "text": text})
        elif section in ("FIG", "TABLE") or ptype.startswith(("fig", "table")):
            kind = "table" if section == "TABLE" or ptype.startswith("table") else "figure"
            key = (kind, inf.get("id") or f"{kind}_{len(floats)}")
            if key not in floats:
                floats[key] = {"kind": kind, "section_type": section, "label": inf.get("id"),
                               "caption": [], "footnote": [], "html": None}
                blocks.append(floats[key])
            if ptype == "table" and inf.get("xml"):
                floats[key]["html"] = table_html(inf["xml"])
            elif text:
                floats[key]["caption" if "caption" in ptype else "footnote"].append(text)
        elif text:
            if ptype == "ref":
                block = {"kind": "reference"}
            elif "title" in ptype:
                block = {"kind": "heading", "level": int(m[1]) if (m := re.fullmatch(r"title_(\d+)", ptype)) else 1}
            elif ptype in ("paragraph", "abstract"):
                block = {"kind": "paragraph"}
            else:
                block = {"kind": "other", "bioc_type": ptype}
            blocks.append({**block, "section_type": section, "text": text})
    for b in blocks:
        if b["kind"] in ("figure", "table"):
            b["caption"], b["footnote"] = " ".join(b["caption"]), " ".join(b["footnote"])
        b["core"] = b["kind"] in ("heading", "paragraph") and b["section_type"] in CORE_SECTIONS
    return meta, blocks


def shingles(text, n=5):
    # Numbers and single characters dropped: inline citations and symbols in custom PDF fonts (P<0.05 -> "po0 05").
    words = [w for w in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", text).lower()) if len(w) > 1 and not w.isdigit()]
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}  # empty if < n words (glossary/list items)


def version_match(blocks, pdf_path):
    with pymupdf.open(pdf_path) as pdf:
        raw, n_pages = "\n".join(page.get_text() for page in pdf), pdf.page_count
    raw = re.sub(r"\xad\s*", "", raw)  # soft hyphens, incl. Wiley's "malig\xad nancies"
    pdf_grams = shingles(re.sub(r"(\w)-\n(\w)", r"\1\2", raw))  # re-join words hyphenated across lines
    paras = [g for b in blocks if b["core"] and b["kind"] == "paragraph" if (g := shingles(b["text"]))]
    found = sum(len(g & pdf_grams) / len(g) >= PARA_FOUND for g in paras)
    return (found / len(paras) if paras else 0.0), n_pages


def render_md(meta, blocks):
    """Readable render for review: [block index:section_type], * = core text."""
    out = [f"<!-- {meta.get('doi')} | {meta.get('pmcid')} -->"]
    for i, b in enumerate(blocks):
        tag = f"`[{i}:{b['section_type'] or '-'}{'*' if b['core'] else ''}]`"
        foot = f"\n\n_{b['footnote']}_" if b.get("footnote") else ""
        if b["kind"] == "title":
            out.append(f"# {b['text']}")
        elif b["kind"] == "heading":
            out.append(f"{'#' * min(b['level'] + 1, 6)} {b['text']}  {tag}")
        elif b["kind"] == "figure":
            out.append(f"{tag} **FIGURE {b['label']}**: {b['caption']}{foot}")
        elif b["kind"] == "table":
            out.append(f"{tag} **TABLE {b['label']}**: {b['caption']}\n\n{b['html'] or '(no table body)'}{foot}")
        else:
            out.append(f"{tag} {b['text']}")
    return "\n\n".join(out) + "\n"


manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
for col in ("core_paragraphs", "figures", "tables", "pdf_pages", "version_match", "selected"):
    manifest[col] = ""

for idx, r in manifest.iterrows():
    meta, blocks = parse_bioc(GT / "raw" / f"{r['id']}.xml")
    sections = {b["section_type"] for b in blocks if b["core"]}
    n_core = sum(b["core"] and b["kind"] == "paragraph" for b in blocks)
    manifest.loc[idx, ["pmcid", "core_paragraphs", "figures", "tables"]] = [meta.get("pmcid", ""), str(n_core),
        str(sum(b["kind"] == "figure" for b in blocks)), str(sum(b["kind"] == "table" for b in blocks))]

    pdf = next((p for p in (ROOT / "pdfs" / f"{r['id']}.pdf", ROOT / "pdfs" / "manual" / f"{r['id']}.pdf") if p.exists()), None)
    if "INTRO" not in sections or not sections & {"METHODS", "RESULTS", "DISCUSS"}:
        status, reason = "excluded", f"structure: core sections {sorted(sections)}"
    elif n_core < MIN_CORE_PARAGRAPHS:
        status, reason = "excluded", f"structure: {n_core} core paragraphs"
    elif pdf is None:
        status, reason = "awaiting_pdf", ""
    else:
        match, pages = version_match(blocks, pdf)
        manifest.loc[idx, ["version_match", "pdf_pages", "pdf_source"]] = [f"{match:.3f}", str(pages), pdf.parent.name]
        status, reason = ("pass", "") if match >= MIN_VERSION_MATCH else ("excluded", f"version: {match:.2f} core paragraphs in PDF")
    manifest.loc[idx, ["status", "reason"]] = [status, reason]

    (GT / f"{r['id']}.json").write_text(json.dumps({"id": r["id"], "publisher": r["publisher"], **meta, "blocks": blocks},
                                                  ensure_ascii=False, indent=1), encoding="utf-8")
    (GT / f"{r['id']}.md").write_text(render_md(meta, blocks), encoding="utf-8")

for publisher, n in TARGET.items():
    manifest.loc[manifest[(manifest.publisher == publisher) & (manifest.status == "pass")].index[:n], "selected"] = "yes"
manifest.to_csv(ROOT / "manifest.csv", index=False)
print(manifest.groupby(["publisher", "status"]).size().unstack(fill_value=0).to_string())