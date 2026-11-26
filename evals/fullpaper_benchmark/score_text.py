# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "rapidfuzz", "tabulate"]
# ///
"""
Score core text of full-paper conversions against the BioC GT, one paragraph at a time.

    uv run evals/fullpaper_benchmark/score_text.py fullpaper_mineru_standard_cuda fullpaper_marker_balanced_cuda

OmniDocBench's quick_match mis-pairs paragraphs at full-paper scale, so each GT core paragraph/heading is instead aligned
to its best-matching span anywhere in the converter's Markdown (rapidfuzz partial alignment). Text is normalised as in
OmniDocBench (HTML tags dropped, lower-cased, only letters and digits kept). Per block: normalised edit distance (ED) to
that span; a block is "found" if ED <= FOUND_ED. A paragraph is "present" if found, found once digits are ignored
(BioC drops citation labels), or >= PRESENT_GRAMS of its word 5-grams occur in the Markdown (paragraph interrupted by a
figure, table, header or footer). Reading order: edit distance between the GT order of found paragraphs and their order
in the Markdown. Table TEDS is taken from the OmniDocBench scores (tables are matched separately).
Writes results/text_scores.csv (per block) and prints per-publisher summaries.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).parent
BENCH = ROOT.parent / "parser_benchmark"
FOUND_ED = 0.2
PRESENT_GRAMS = 0.8


def norm(text):
    text = re.sub(r"</?[a-zA-Z][^<>]*>", "", unicodedata.normalize("NFKC", text)).lower()  # tags only, not "P < 0.05"
    return re.sub(r"[^0-9a-z]", "", text)


def best_ed(gt, pred):
    al = fuzz.partial_ratio_alignment(gt, pred)
    span = pred[al.dest_start:al.dest_end] if al else ""
    return al, span, Levenshtein.distance(gt, span)


def shingles(text, n=5):  # as in build_gt.py
    words = [w for w in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", text).lower()) if len(w) > 1 and not w.isdigit()]
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
selected = manifest[manifest.selected == "yes"].set_index("id")
rows, order = [], []
for run in sys.argv[1:]:
    for pid, paper in selected.iterrows():
        md = (BENCH / "preds" / "fullpaper" / run / f"{pid}.md").read_text(encoding="utf-8")
        pred, pred_grams = norm(md), shingles(md)
        pred_nodigits = re.sub(r"\d", "", pred)
        positions = []
        for i, b in enumerate(json.loads((ROOT / "gt" / f"{pid}.json").read_text(encoding="utf-8"))["blocks"]):
            if not b["core"] or not (gt := norm(b["text"])):
                continue
            al, span, edits = best_ed(gt, pred)
            ed = edits / max(len(gt), len(span))
            present = ed <= FOUND_ED
            if not present and (gt_nodigits := re.sub(r"\d", "", gt)):
                _, span_nd, edits_nd = best_ed(gt_nodigits, pred_nodigits)
                present = edits_nd / max(len(gt_nodigits), len(span_nd)) <= FOUND_ED
            if not present and (g := shingles(b["text"])):
                present = len(g & pred_grams) / len(g) >= PRESENT_GRAMS
            rows.append({"run": run, "id": pid, "publisher": paper.publisher, "kind": b["kind"], "block": i,
                         "gt_chars": len(gt), "edits": edits, "ed": ed, "present": present})
            if b["kind"] == "paragraph" and ed <= FOUND_ED:
                positions.append((al.dest_start, len(positions)))
        pred_order = [k for _, k in sorted(positions)]
        order.append({"run": run, "id": pid, "publisher": paper.publisher,
                      "order_ed": Levenshtein.normalized_distance(list(range(len(pred_order))), pred_order)})

df = pd.DataFrame(rows)
(ROOT / "results").mkdir(exist_ok=True)
df.to_csv(ROOT / "results" / "text_scores.csv", index=False)
paper = (df[df.kind == "paragraph"].groupby(["run", "publisher", "id"])
         .apply(lambda g: pd.Series({"text_ed": g.edits.sum() / g.gt_chars.sum(), "found": (g.ed <= FOUND_ED).mean(),
                                     "present": g.present.mean()}))
         .reset_index().merge(pd.DataFrame(order), on=["run", "publisher", "id"]))
head = df[df.kind == "heading"].groupby(["run", "publisher"]).ed.apply(lambda e: (e <= FOUND_ED).mean())

for run in sys.argv[1:]:
    p = paper[paper.run == run]
    s = p.groupby("publisher")[["text_ed", "found", "present", "order_ed"]].mean()
    s.loc["all"] = p[["text_ed", "found", "present", "order_ed"]].mean()
    s["headings_found"] = head[run].reindex(s.index)
    s.loc["all", "headings_found"] = (df[(df.run == run) & (df.kind == "heading")].ed <= FOUND_ED).mean()
    m = json.loads(next((BENCH / "results" / "scores" / run / "all").glob("*metric_result.json")).read_text())
    teds = m["table"]["page"]["TEDS"]
    s["table_teds"] = [teds.get("ALL" if k == "all" else f"data_source: {k}") for k in s.index]
    print(f"\n{run}  (text ED and order ED: mean over papers; found = share of core paragraphs with ED <= {FOUND_ED})")
    print(s.round(3).to_markdown())
