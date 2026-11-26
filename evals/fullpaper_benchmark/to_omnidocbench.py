# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas"]
# ///
"""
Convert the selected full-paper GT to OmniDocBench's end-to-end format (one pseudo-page per paper) so it can be scored
with parser_benchmark/score.py. Only core text (INTRO/METHODS/RESULTS/DISCUSS/CONCL headings and paragraphs) and tables
are scored; all other GT text is given categories OmniDocBench matches but ignores, so the predicted abstract,
references, captions etc. are absorbed rather than penalised.

    uv run evals/fullpaper_benchmark/to_omnidocbench.py

Writes gt/omnidocbench.json and parser_benchmark/data/fullpaper.txt (selected PDF paths for the run_*.py scripts).
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent

manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
selected = manifest[manifest.selected == "yes"]
pages, pdfs = [], []
for r in selected.itertuples():
    dets = []
    for b in json.loads((ROOT / "gt" / f"{r.id}.json").read_text(encoding="utf-8"))["blocks"]:
        if b["kind"] in ("figure", "table"):
            items = [(f"{b['kind']}_caption", "text", b["caption"]), (f"{b['kind']}_footnote", "text", b["footnote"])]
            if b["kind"] == "table" and b["html"]:
                items.insert(1, ("table", "html", b["html"]))
        elif b["core"]:
            items = [("title" if b["kind"] == "heading" else "text_block", "text", b["text"])]
        else:
            items = [("page_footnote", "text", b["text"])]  # matched but not scored
        for cat, field, value in items:
            if value:
                dets.append({"category_type": cat, "poly": [0, 0, 1, 0, 1, 1, 0, 1], "ignore": False,
                             "order": len(dets), "anno_id": f"b{len(dets)}", "attribute": {}, field: value})
    # .png suffix: OmniDocBench strips the last "_" part from image names without one.
    pages.append({"layout_dets": dets, "extra": {"relation": []},
                  "page_info": {"page_no": 0, "height": 1, "width": 1, "image_path": f"{r.id}.png",
                                "page_attribute": {"data_source": r.publisher, "language": "english",
                                                   "layout": "full_paper", "special_issue": [], "subset": r.query}}})
    pdfs.append(ROOT / "pdfs" / ("manual" if r.pdf_source == "manual" else "") / f"{r.id}.pdf")

(ROOT / "gt" / "omnidocbench.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
(ROOT.parent / "parser_benchmark" / "data" / "fullpaper.txt").write_text("\n".join(map(str, pdfs)), encoding="utf-8")
print(f"{len(pages)} papers")