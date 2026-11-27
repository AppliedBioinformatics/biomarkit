# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas==3.1.1", "rapidfuzz==3.14.6", "tabulate", "tiktoken==0.12.0"]
# ///
"""
Token reduction with standardise_text()'s default keep_ options (Supplementary Table 15).

    uv run evals/fullpaper_benchmark/score_defaults.py

Compares the defaults Markdown from run_defaults.py with the all_kept Markdown from run_flags.py for each paper.
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
ENC = tiktoken.get_encoding("o200k_base")


def norm(text):  # as in score_text.py
    text = re.sub(r"</?[a-zA-Z][^<>]*>", "", unicodedata.normalize("NFKC", text)).lower()
    return re.sub(r"[^0-9a-z]", "", text)


def shingles(text, n=5):  # as in build_gt.py
    words = [w for w in re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKC", text).lower()) if len(w) > 1 and not w.isdigit()]
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


class Doc:  # as in score_flags.py
    def __init__(self, md):
        self.norm, self.grams, self.tokens = norm(md), shingles(md), len(ENC.encode(md))

    def has(self, text):
        if (g := shingles(text)) and len(g & self.grams) / len(g) >= PRESENT_GRAMS:
            return True
        if not (gt := norm(text)):
            return False
        al = fuzz.partial_ratio_alignment(gt, self.norm)
        span = self.norm[al.dest_start:al.dest_end] if al else ""
        return Levenshtein.distance(gt, span) / max(len(gt), len(span)) <= FOUND_ED


manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
rows = []
for route in ("pdf", "bioc"):
    for r in manifest[manifest.selected == "yes"].itertuples():
        base = Doc((PREDS / route / "all_kept" / f"{r.id}.md").read_text(encoding="utf-8"))
        doc = Doc((PREDS / route / "defaults" / f"{r.id}.md").read_text(encoding="utf-8"))
        gt = json.loads((ROOT / "gt" / f"{r.id}.json").read_text(encoding="utf-8"))["blocks"]
        core = [b["text"] for b in gt if b["kind"] == "paragraph" and b["core"] and base.has(b["text"])]
        rows.append({"route": route, "id": r.id, "publisher": r.publisher, "tokens_before": base.tokens,
                     "tokens_after": doc.tokens, "core": len(core), "core_lost": sum(not doc.has(t) for t in core)})

df = pd.DataFrame(rows)
df["tokens_removed"] = df.tokens_before - df.tokens_after
df["tokens_removed_pct"] = 100 * df.tokens_removed / df.tokens_before
(ROOT / "results").mkdir(exist_ok=True)
df.to_csv(ROOT / "results" / "defaults_tokens.csv", index=False)


def summarise(g):
    pct = g.tokens_removed_pct
    return pd.Series({"papers": len(g), "tokens_before": g.tokens_before.mean(), "tokens_after": g.tokens_after.mean(),
                      "tokens_removed": g.tokens_removed.mean(), "pct_mean": pct.mean(), "pct_median": pct.median(),
                      "pct_q1": pct.quantile(0.25), "pct_q3": pct.quantile(0.75), "pct_min": pct.min(),
                      "pct_max": pct.max(), "core_lost_pct": 100 * g.core_lost.sum() / g.core.sum()})


for route, g in df.groupby("route", sort=False):
    s = g.groupby("publisher").apply(summarise)
    s.loc["all"] = summarise(g)
    print(f"\n{route}: standardise_text() defaults vs all options kept")
    print(s.round(1).to_markdown())
