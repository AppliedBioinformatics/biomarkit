# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "rapidfuzz", "tabulate"]
# ///
"""
Score core paragraphs and headings of full-paper conversions against the BioC GT (Supplementary Tables 8-9).

    uv run evals/fullpaper_benchmark/score_text.py fullpaper_mineru_standard_cuda fullpaper_marker_balanced_cuda

Run name "gt" scores the GT itself (sanity check).
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


def gt_markdown(blocks):
    """GT rendered as Markdown, for the sanity-check run "gt"."""
    out = []
    for b in blocks:
        if b["kind"] == "title":
            out.append(f"# {b['text']}")
        elif b["kind"] == "heading":
            out.append(f"{'#' * min(b['level'] + 1, 6)} {b['text']}")
        else:
            out.append(b.get("text") or b.get("caption") or "")
    return "\n\n".join(out)


def heading_match(gt, cand):
    """'full' if the candidate line is the heading (ED <= FOUND_ED), 'affix' if it starts/ends with it, else None."""
    if Levenshtein.normalized_distance(gt, cand) <= FOUND_ED:
        return "full"
    if len(cand) > len(gt):
        for part in (cand[:len(gt)], cand[-len(gt):]):
            if Levenshtein.normalized_distance(gt, part) <= FOUND_ED:
                return "affix"
    return None


def score_headings(blocks, md):
    lines = [(i, len(m[1]), norm(m[2])) for i, m in
             enumerate(re.match(r"^(#{1,6})\s+(.*)", l) for l in md.splitlines()) if m and norm(m[2])]
    cands = [(k, [k], t) for k, (_, _, t) in enumerate(lines)]
    cands += [(k, [k, k + 1], lines[k][2] + lines[k + 1][2]) for k in range(len(lines) - 1)]
    core = [(i, b) for i, b in enumerate(blocks) if b["kind"] == "heading" and b["core"] and norm(b["text"])]
    rows, used, last = [], set(), -1
    for i, b in core:
        gt, hit = norm(b["text"]), None
        matches = [(k, ks, heading_match(gt, t)) for k, ks, t in cands]
        for after, kind in ((True, "full"), (True, "affix"), (False, "full"), (False, "affix")):
            hit = next(((k, ks, kd) for k, ks, kd in matches if kd == kind and (k >= last if after else True)
                        and (kind == "affix" or not set(ks) & used)), None)
            if hit:
                break
        if hit:
            last = hit[0]
            used |= set(hit[1])
        rows.append({"block": i, "level": b["level"], "found": bool(hit), "merged": bool(hit) and hit[2] == "affix",
                     "md_line": lines[hit[0]][0] if hit else None, "md_level": lines[hit[0]][1] if hit else None})
    other = [norm(b["text"]) for b in blocks if b["kind"] in ("title", "heading") and not b["core"] and norm(b["text"])]
    found = [r for r in rows if r["found"]]
    # Precision only within the core text span: front/back-matter headings BioC doesn't mark (Abstract, References,
    # Author details) would otherwise count as spurious.
    lo, hi = (min(r["md_line"] for r in found), max(r["md_line"] for r in found)) if found else (0, -1)
    correct = [k in used or any(heading_match(g, t) for g in other)
               for k, (line, _, t) in enumerate(lines) if lo <= line <= hi]
    ranked = [n for _, n in sorted((r["md_line"], n) for n, r in enumerate(found))]
    sign = lambda x: (x > 0) - (x < 0)
    pairs = [(a, b) for a, b in zip(found, found[1:]) if a["level"] != b["level"]]
    paper = {"heading_recall": len(found) / len(rows) if rows else None,
             "heading_precision": sum(correct) / len(correct) if correct else None,
             "heading_order_ed": Levenshtein.normalized_distance(list(range(len(ranked))), ranked) if found else None,
             "hierarchy": sum(sign(b["level"] - a["level"]) == sign(b["md_level"] - a["md_level"])
                                    for a, b in pairs) / len(pairs) if pairs else None}
    return rows, paper


manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
selected = manifest[manifest.selected == "yes"].set_index("id")
rows, order, head_rows, head_paper = [], [], [], []
for run in sys.argv[1:]:
    for pid, paper in selected.iterrows():
        blocks = json.loads((ROOT / "gt" / f"{pid}.json").read_text(encoding="utf-8"))["blocks"]
        md = gt_markdown(blocks) if run == "gt" else \
            (BENCH / "preds" / "fullpaper" / run / f"{pid}.md").read_text(encoding="utf-8")
        pred, pred_grams = norm(md), shingles(md)
        pred_nodigits = re.sub(r"\d", "", pred)
        h_rows, h_paper = score_headings(blocks, md)
        head_rows += [{"run": run, "id": pid, "publisher": paper.publisher, **r} for r in h_rows]
        head_paper.append({"run": run, "id": pid, "publisher": paper.publisher, **h_paper})
        positions = []
        for i, b in enumerate(blocks):
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
         .reset_index().merge(pd.DataFrame(order), on=["run", "publisher", "id"])
         .merge(pd.DataFrame(head_paper), on=["run", "publisher", "id"]))
heads = pd.DataFrame(head_rows).merge(df[df.kind == "heading"][["run", "id", "block", "ed"]], on=["run", "id", "block"])
heads["demoted"] = ~heads.found & (heads.ed <= FOUND_ED)  # in the text, but not as a heading line
heads.drop(columns="ed").to_csv(ROOT / "results" / "heading_scores.csv", index=False)

cols = ["text_ed", "found", "present", "order_ed", "heading_recall", "heading_precision", "heading_order_ed",
        "hierarchy"]
for run in sys.argv[1:]:
    p = paper[paper.run == run]
    s = p.groupby("publisher")[cols].mean()
    s.loc["all"] = p[cols].mean()
    h = heads[heads.run == run]
    print(f"\n{run} headings: {len(h)} GT core, {int(h.found.sum())} found ({int(h.merged.sum())} merged), "
          f"{int(h.demoted.sum())} demoted to text")
    metric = next((BENCH / "results" / "scores" / run / "all").glob("*metric_result.json"), None)
    if metric:
        teds = json.loads(metric.read_text())["table"]["page"]["TEDS"]
        s["table_teds"] = [teds.get("ALL" if k == "all" else f"data_source: {k}") for k in s.index]
    print(f"\n{run}  (text ED and order ED: mean over papers; found = share of core paragraphs with ED <= {FOUND_ED})")
    print(s.round(3).to_markdown())
