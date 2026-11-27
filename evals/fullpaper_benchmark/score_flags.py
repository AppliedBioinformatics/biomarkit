# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas==3.1.1", "rapidfuzz==3.14.6", "tabulate", "tiktoken==0.12.0"]
# ///
"""
Score keep_figures / keep_tables / keep_references (Supplementary Table 11) against the BioC GT.

    uv run evals/fullpaper_benchmark/score_flags.py

Reads the Markdown written by run_flags.py; each condition is compared with all_kept for the same paper. Also
compares keep_references with truncating at the first References heading (Supplementary Table 12).
"""
import json
import re
import unicodedata
from pathlib import Path

import pandas as pd
import tiktoken
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).parent
PREDS = ROOT.parent / "parser_benchmark" / "preds" / "flags"
FOUND_ED = 0.2
PRESENT_GRAMS = 0.8
TARGETS = {"no_figures": {"figure"}, "no_tables": {"table"}, "no_references": {"reference"},
           "no_all3": {"figure", "table", "reference"},
           "no_boilerplate": set(), "no_inline_latex": set()}  # no BioC target: scored for core-text safety only
ENC = tiktoken.get_encoding("o200k_base")
SECTIONS = ("INTRO", "METHODS", "RESULTS", "DISCUSS", "CONCL")


def norm(text):  # as in score_text.py
    text = re.sub(r"</?[a-zA-Z][^<>]*>", "", unicodedata.normalize("NFKC", text)).lower()
    return re.sub(r"[^0-9a-z]", "", text)


def shingles(text, n=5):  # as in build_gt.py
    words = [w for w in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", text).lower()) if len(w) > 1 and not w.isdigit()]
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


class Doc:
    def __init__(self, md):
        self.md, self.norm, self.grams, self.tokens = md, norm(md), shingles(md), len(ENC.encode(md))

    def has(self, text):
        """Present: >= PRESENT_GRAMS of the unit's word 5-grams, or normalised ED <= FOUND_ED to its best span.
        A table body (HTML) is matched as one cell sequence by edit distance only, so a caption or phrase repeated
        in the body text cannot make a removed table look present."""
        is_table = text.lstrip().startswith("<table")
        if not is_table and (g := shingles(text)) and len(g & self.grams) / len(g) >= PRESENT_GRAMS:
            return True
        if not (gt := norm(text)):
            return False
        return self.ed(gt) <= FOUND_ED

    def ed(self, gt):
        """Normalised edit distance of normalised text gt to its best-matching span."""
        al = fuzz.partial_ratio_alignment(gt, self.norm)
        span = self.norm[al.dest_start:al.dest_end] if al else ""
        return Levenshtein.distance(gt, span) / max(len(gt), len(span))


def units(blocks):
    """GT units scored per paper: core paragraphs and figure / table / reference targets."""
    out = []
    for b in blocks:
        if b["kind"] == "paragraph" and b["core"]:
            out.append((f"core_{b['section_type']}", [b["text"]]))
        elif b["kind"] == "figure" and b["caption"]:
            out.append(("figure", [b["caption"]]))
        elif b["kind"] == "table":
            body = b["html"] or b["caption"]  # table body (all cells, row order); caption only if no body
            if body:
                out.append(("table", [body]))
        elif b["kind"] == "reference" and b["text"]:
            out.append(("reference", [b["text"]]))
    return out


manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
selected = manifest[manifest.selected == "yes"]
rows = []
for route in ("pdf", "bioc"):
    for r in selected.itertuples():
        base_path = PREDS / route / "all_kept" / f"{r.id}.md"
        if not base_path.exists():
            continue
        base = Doc(base_path.read_text(encoding="utf-8"))
        gt = json.loads((ROOT / "gt" / f"{r.id}.json").read_text(encoding="utf-8"))["blocks"]
        scored = [(kind, texts) for kind, texts in units(gt) if any(base.has(t) for t in texts)]  # in baseline
        for cond, targets in TARGETS.items():
            doc = Doc((PREDS / route / cond / f"{r.id}.md").read_text(encoding="utf-8"))
            gone = [(kind, texts) for kind, texts in scored if not any(doc.has(t) for t in texts)]
            core_lost = [texts[0] for kind, texts in gone if kind.startswith("core")]
            # Inline LaTeX is replaced inside sentences, so also measure how far core paragraphs move away from the GT.
            core_eds = [(base.ed(norm(t[0])), doc.ed(norm(t[0]))) for k, t in scored
                        if cond == "no_inline_latex" and k.startswith("core") and norm(t[0])]
            rows.append({"route": route, "condition": cond, "id": r.id, "publisher": r.publisher,
                         "targets": sum(k in targets for k, _ in scored), "removed": sum(k in targets for k, _ in gone),
                         "core": sum(k.startswith("core") for k, _ in scored), "core_lost": len(core_lost),
                         **{f"core_{s}": sum(k == f"core_{s}" for k, _ in scored) for s in SECTIONS},
                         **{f"lost_{s}": sum(k == f"core_{s}" for k, _ in gone) for s in SECTIONS},
                         "tokens_before": base.tokens, "tokens_after": doc.tokens,
                         "core_tokens_lost": sum(len(ENC.encode(t)) for t in core_lost),
                         "core_ed_change": sum(d - b for b, d in core_eds),
                         "core_found_base": sum(b <= FOUND_ED for b, _ in core_eds),
                         "core_unfound": sum(b <= FOUND_ED < d for b, d in core_eds)})

df = pd.DataFrame(rows)
df["tokens_removed"] = df.tokens_before - df.tokens_after
df["tokens_removed_pct"] = 100 * df.tokens_removed / df.tokens_before
(ROOT / "results").mkdir(exist_ok=True)
df.to_csv(ROOT / "results" / "flag_scores.csv", index=False)


def summarise(g):
    return pd.Series({"papers": len(g), "targets": g.targets.sum(),
                      "removed_pct": 100 * g.removed.sum() / g.targets.sum() if g.targets.sum() else None,
                      "core_lost_pct": 100 * g.core_lost.sum() / g.core.sum(),
                      "tokens_removed": g.tokens_removed.mean(), "tokens_removed_pct": g.tokens_removed_pct.mean(),
                      "core_tokens_lost": g.core_tokens_lost.mean(),
                      "core_ed_change": g.core_ed_change.sum() / g.core.sum(),
                      "core_unfound_pct": 100 * g.core_unfound.sum() / max(g.core_found_base.sum(), 1),
                      **{f"lost_{s}_pct": 100 * g[f"lost_{s}"].sum() / max(g[f"core_{s}"].sum(), 1) for s in SECTIONS}})


for (route, cond), g in df.groupby(["route", "condition"], sort=False):
    s = g.groupby("publisher").apply(summarise)
    s.loc["all"] = summarise(g)
    print(f"\n{route} / {cond}  (removed and core lost: pooled over units; tokens: mean per paper)")
    print(s.round(2).to_markdown())


# Comparison (Supplementary Table 12): truncating at the first References heading vs keep_references=False, both
# applied to the same all_kept Markdown of each publisher PDF.
REFS_HEADING = re.compile(r"^\s*(?:#+\s*)?(?:\d+\.?\s*)?(?:references?|bibliography|literature cited|references cited)"
                          r"\s*[:.]?\s*$", re.I | re.M)
comp = []
for r in selected.itertuples():
    path = PREDS / "pdf" / "all_kept" / f"{r.id}.md"
    if not path.exists():
        continue
    md = path.read_text(encoding="utf-8")
    m = REFS_HEADING.search(md)
    base = Doc(md)
    gt = json.loads((ROOT / "gt" / f"{r.id}.json").read_text(encoding="utf-8"))["blocks"]
    scored = [(k, t) for k, t in units(gt) if any(base.has(x) for x in t)]
    back = [b["text"] for b in gt if b["kind"] == "paragraph" and not b["core"] and base.has(b["text"])]
    methods = {"truncate": Doc(md[:m.start()] if m else md),
               "biomarkit": Doc((PREDS / "pdf" / "no_references" / f"{r.id}.md").read_text(encoding="utf-8"))}
    for method, doc in methods.items():
        gone = [(k, t) for k, t in scored if not any(doc.has(x) for x in t)]
        core_lost = [t[0] for k, t in gone if k.startswith("core")]
        comp.append({"method": method, "id": r.id, "publisher": r.publisher, "heading_found": bool(m),
                     "tokens_removed": base.tokens - doc.tokens,
                     "tokens_removed_pct": 100 * (base.tokens - doc.tokens) / base.tokens,
                     "refs": sum(k == "reference" for k, _ in scored),
                     "refs_removed": sum(k == "reference" for k, _ in gone),
                     "core": sum(k.startswith("core") for k, _ in scored), "core_lost": len(core_lost),
                     "core_tokens_lost": sum(len(ENC.encode(t)) for t in core_lost),
                     "sections_lost": ",".join(sorted({k[5:] for k, _ in gone if k.startswith("core")})),
                     "figures_lost": sum(k == "figure" for k, _ in gone),
                     "tables_lost": sum(k == "table" for k, _ in gone),
                     "back": len(back), "back_removed": sum(not doc.has(t) for t in back)})
cmp_df = pd.DataFrame(comp)
cmp_df.to_csv(ROOT / "results" / "refs_truncate_vs_typed.csv", index=False)


def compare(g):
    return pd.Series({"papers": len(g), "papers_tokens_removed": int((g.tokens_removed > 0).sum()),
                      "papers_core_lost": int((g.core_lost > 0).sum()),
                      "refs_removed_pct": 100 * g.refs_removed.sum() / g.refs.sum(),
                      "core_lost": int(g.core_lost.sum()), "core_lost_pct": 100 * g.core_lost.sum() / g.core.sum(),
                      "figures_lost": int(g.figures_lost.sum()), "tables_lost": int(g.tables_lost.sum()),
                      "back_removed_pct": 100 * g.back_removed.sum() / max(g.back.sum(), 1),
                      "tokens_removed": g.tokens_removed.mean(), "tokens_removed_pct": g.tokens_removed_pct.mean()})


for method, g in cmp_df.groupby("method", sort=False):
    s = g.groupby("publisher").apply(compare)
    s.loc["all"] = compare(g)
    print(f"\nReferences removal by {method} (PDF, all_kept baseline)")
    print(s.round(2).to_markdown())
lost_cols = ["method", "id", "core_lost", "core_tokens_lost", "sections_lost"]
print(cmp_df[cmp_df.core_lost > 0][lost_cols].to_markdown(index=False))
