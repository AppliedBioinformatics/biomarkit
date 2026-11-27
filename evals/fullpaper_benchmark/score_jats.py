# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas==3.1.1", "rapidfuzz==3.14.6", "tabulate"]
# ///
"""
Label what keep_boilerplate and keep_inline_latex remove, using each article's full JATS XML (Supplementary Table 13).

    uv run evals/fullpaper_benchmark/score_jats.py

Boilerplate blocks (MinerU page_* / index blocks; BioC footnote / peer-review blocks) are labelled by the JATS element
they match; inline LaTeX spans by whether JATS marks them as <inline-formula>. Writes results/jats_boilerplate.csv,
results/jats_inline.csv and the review samples results/audit_boilerplate.csv and results/audit_inline_latex.csv.
"""
import collections
import glob
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).parent
CORPUS = ROOT / "corpus" / "intermediates"
FOUND_ED = 0.2
BOILERPLATE = {"page_header", "page_footer", "page_number", "page_footnote", "page_aside_text", "index"}
# JATS elements holding the front/back matter that page furniture reproduces, by label.
JATS_LABELS = {
    "affiliation": {"aff"},
    "author note / correspondence": {"author-notes", "corresp"},
    "licence / copyright": {"permissions"},
    "dates": {"history", "pub-date"},
    "footnote": {"fn"},
    "journal / article metadata": {"journal-title", "article-title", "alt-title", "contrib", "volume", "issue", "fpage",
                                   "lpage", "elocation-id", "article-id", "publisher-name", "issn", "subject",
                                   "kwd-group", "self-uri", "journal-id"},
}
CITATION_LINE = re.compile(r"doi|www\.|https?://|issn|journal|volume|vol\.|all rights reserved|©", re.I)
BACK = {"ack", "app", "ref-list", "notes", "glossary", "back"}


def norm(text):  # as in score_text.py
    text = re.sub(r"</?[a-zA-Z][^<>]*>", "", unicodedata.normalize("NFKC", text)).lower()
    return re.sub(r"[^0-9a-z]", "", text)


def words(text):
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", text).lower())


def local(tag):
    return tag.rsplit("}", 1)[-1]  # PMC OAI copies carry the JATS namespace, Europe PMC copies do not


def text_of(el):
    return " ".join("".join(el.itertext()).split())


def matches(needle, haystack):
    """Normalised needle found in normalised haystack within FOUND_ED (partial alignment)."""
    if not needle or not haystack:
        return False
    al = fuzz.partial_ratio_alignment(needle, haystack) if len(needle) <= len(haystack) else None
    span = haystack[al.dest_start:al.dest_end] if al else ""
    return bool(al) and Levenshtein.distance(needle, span) / max(len(needle), len(span)) <= FOUND_ED


class Jats:
    def __init__(self, path):
        root = ET.parse(path).getroot()
        for el in root.iter():
            el.tag = local(el.tag)
        self.pools = {k: set() for k in JATS_LABELS}
        self.pool_text = {}
        for label, tags in JATS_LABELS.items():
            texts = [text_of(el) for el in root.iter() if el.tag in tags]
            texts += [v for el in root.iter() for k, v in el.attrib.items() if local(k) == "article-type"]
            for t in texts:
                self.pools[label] |= set(words(t))
            self.pool_text[label] = norm(" ".join(texts))
        body = root.find(".//body")
        self.captions = norm(" ".join(text_of(c) for c in root.iter("caption")))
        caption_ps = {id(p) for c in root.iter("caption") for p in c.iter("p")}
        body_ps = [text_of(p) for p in body.iter("p") if id(p) not in caption_ps] if body is not None else []
        self.body = norm(" ".join(body_ps))
        self.back = norm(" ".join(text_of(el) for el in root.iter() if el.tag in BACK))
        self.formulas = {s for el in root.iter() if el.tag == "inline-formula" if (s := symbols(text_of(el)))}
        assert self.body and self.pools["affiliation"], f"{path}: JATS parsed without body or affiliations"


def label_block(text, btype, repeated, jats):
    t, w = text.strip(), words(text)
    if btype == "page_number" or re.fullmatch(r"(page\s*)?\d+(\s*(of|/)\s*\d+)?", t.lower()):
        return "page number"
    if w:
        for label, pool in jats.pools.items():
            if len(set(w) & pool) / len(set(w)) >= 0.8 or matches(norm(t), jats.pool_text[label]):
                return label
    if "@" in t:
        return "author note / correspondence"
    if CITATION_LINE.search(t):
        return "journal / article metadata"
    if repeated:
        return "repeated running head / footer"
    if len(w) >= 5 and matches(norm(t), jats.captions):
        return "figure / table caption"
    if len(w) >= 8 and matches(norm(t), jats.body):
        return "body content"
    if len(w) >= 5 and matches(norm(t), jats.back):
        return "back matter"
    if len(w) <= 3:
        return "short label"
    return "unmatched"


def symbols(latex):
    """LaTeX / MathML text reduced to letters and digits, so both renderings of the same maths compare equal."""
    return norm(re.sub(r"\\[a-zA-Z]+", " ", latex))


UNIT = re.compile(r"\\mu|\\circ|°|%|\\%|\\mathrm\s*\{\s*[a-zA-Z]{1,4}\s*\}|\\times\s*1\s*0")


def span_class(latex):
    if re.search(r"[=<>≤≥±]|\\(le|ge|leq|geq|pm|approx|sim|lt|gt)\b", latex):
        return "statistic / relation"
    if re.search(r"\d", latex) and UNIT.search(latex):
        return "unit / number"
    if re.fullmatch(r"[\d\s.,{}^_~\\]*", re.sub(r"\\(mathrm|mathbf|text|mathit)", "", latex)):
        return "unit / number"
    if len(symbols(latex)) <= 4:
        return "symbol / variable"
    return "formula / expression"


def inline_spans(block):
    content = block.get("content") or {}
    fields = [content.get(k) for k in ("paragraph_content", "title_content", "algorithm_content")]
    fields += [it["item_content"] for it in content.get("list_items", [])]
    for spans in fields:
        if not spans:
            continue
        for i, s in enumerate(spans):
            if s.get("type") == "equation_inline":
                near = spans[max(0, i - 3):i + 4]
                ctx = "".join(x.get("content", "") for x in near if isinstance(x.get("content"), str))
                yield s["content"], ctx


manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
selected = manifest[manifest.selected == "yes"]
blocks_out, spans_out = [], []
for r in selected.itertuples():
    jats = Jats(ROOT / "gt" / "jats" / f"{r.id}.xml")
    for route, stem in (("pdf", r.id), ("bioc", f"bioc_{r.id}")):
        page_blocks = json.load(open(glob.glob(str(CORPUS / stem / "auto" / "*_content_list_v2.json"))[0],
                                     encoding="utf-8"))
        flat = [(p, b) for p, page in enumerate(page_blocks) for b in page]
        texts = {}
        for p, b in flat:
            if b["type"] in BOILERPLATE:
                c = b.get("content") or {}
                spans = (c.get(f"{b['type']}_content")
                         or [s for it in c.get("list_items", []) for s in it["item_content"]])  # index blocks
                texts[(p, id(b))] = " ".join(s.get("content", "") for s in spans if isinstance(s.get("content"), str))
        counts = collections.Counter(norm(t) for t in texts.values())
        for p, b in flat:
            if (p, id(b)) in texts:
                t = texts[(p, id(b))]
                # On the BioC input, page_aside_text blocks are by construction the published peer-review history.
                label = ("peer-review history" if route == "bioc" and b["type"] == "page_aside_text"
                         else label_block(t, b["type"], counts[norm(t)] >= 3, jats))
                blocks_out.append({"route": route, "id": r.id, "publisher": r.publisher, "page": p, "type": b["type"],
                                   "text": t, "label": label})
            if route == "pdf":
                for latex, ctx in inline_spans(b):
                    sym = symbols(latex)
                    jats_math = bool(sym) and (sym in jats.formulas
                                               or (len(sym) >= 3 and any(sym in f for f in jats.formulas)))
                    spans_out.append({"id": r.id, "publisher": r.publisher, "latex": latex, "context": ctx,
                                      "jats_inline_formula": jats_math, "class": span_class(latex)})

bp, sp = pd.DataFrame(blocks_out), pd.DataFrame(spans_out)
(ROOT / "results").mkdir(exist_ok=True)
bp.to_csv(ROOT / "results" / "jats_boilerplate.csv", index=False)
sp.to_csv(ROOT / "results" / "jats_inline.csv", index=False)

# Review samples (seed 0): blocks the JATS could not show to be boilerplate, and random inline spans.
review = bp[(bp.route == "pdf") & bp.label.isin(["body content", "unmatched"])]
review.sample(min(40, len(review)), random_state=0).assign(confirmed_label="").to_csv(
    ROOT / "results" / "audit_boilerplate.csv", index=False)
sp.sample(min(50, len(sp)), random_state=0).assign(confirmed_class="").to_csv(
    ROOT / "results" / "audit_inline_latex.csv", index=False)

for route in ("pdf", "bioc"):
    g = bp[bp.route == route]
    t = pd.crosstab(g.publisher, g.label, margins=True, margins_name="all")
    print(f"\n{route}: boilerplate blocks removed, by JATS label")
    print(t.to_markdown())
    prec = g.groupby("publisher").label.apply(lambda x: 100 * (x != "body content").mean())
    print("precision (% not body content):", prec.round(1).to_dict(),
          "| all:", round(100 * (g.label != "body content").mean(), 1))
print("\npdf: inline LaTeX spans")
print(pd.crosstab(sp.publisher, sp["class"], margins=True, margins_name="all").to_markdown())
print("marked as <inline-formula> in JATS (%):",
      sp.groupby("publisher").jats_inline_formula.mean().mul(100).round(1).to_dict(),
      "| all:", round(100 * sp.jats_inline_formula.mean(), 1))
