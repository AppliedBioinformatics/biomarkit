# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas", "numpy", "tabulate"]
# ///
"""
Collect scorer outputs and timings into the manuscript tables.

    uv run evals/parser_benchmark/summarise.py

Writes results/summary_accuracy_{all,english}.{csv,md} and results/summary_speed.{csv,md}.
Overall = mean of (1 - text ED), table TEDS and (1 - formula ED), x100 (OmniDocBench's own Overall uses formula CDM).
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"
rng = np.random.default_rng(0)


def boot_ci(values, n=2000):
    v = np.asarray(values, dtype=float)
    means = rng.choice(v, size=(n, len(v)), replace=True).mean(axis=1)
    return np.percentile(means, [2.5, 97.5])


def split_tag(tag):
    tool, mode, device = tag.split("_")
    return tool, mode, device


for subset in ("all", "english"):
    rows = []
    for meta_path in sorted(RESULTS.glob("meta_accuracy_*.json")):
        tag = meta_path.stem.removeprefix("meta_accuracy_")
        run_dir = RESULTS / "scores" / tag / subset
        m = json.loads(next(run_dir.glob("*_metric_result.json")).read_text(encoding="utf-8"))
        text_pages = json.loads(next(run_dir.glob("*text_block_per_page_edit.json")).read_text())
        lo, hi = boot_ci(list(text_pages.values()))
        text_ed = m["text_block"]["all"]["Edit_dist"]["ALL_page_avg"]
        formula_ed = m["display_formula"]["all"]["Edit_dist"]["ALL_page_avg"]
        teds = m["table"]["all"]["TEDS"]["all"]
        meta = json.loads(meta_path.read_text())
        timing = pd.read_csv(RESULTS / f"timing_accuracy_{tag}.csv")
        tool, mode, device = split_tag(tag)
        rows.append({"tool": tool, "version": meta["version"], "mode": mode, "device": device,
                     "pages": len(text_pages), "text_ED": round(text_ed, 3),
                     "text_ED_95CI": f"{lo:.3f}-{hi:.3f}", "formula_ED": round(formula_ed, 3),
                     "table_TEDS": round(teds, 3),
                     "table_TEDS_struct": round(m["table"]["all"]["TEDS_structure_only"]["all"], 3),
                     "reading_order_ED": round(m["reading_order"]["all"]["Edit_dist"]["ALL_page_avg"], 3),
                     "overall": round(((1 - text_ed) + teds + (1 - formula_ed)) / 3 * 100, 1),
                     "failures": meta["failures"],
                     "s_per_page_median": round(timing.seconds.median(), 2),
                     "total_min": round((timing.seconds.sum() + meta["load_seconds"]) / 60, 1)})
    if rows:
        df = pd.DataFrame(rows).sort_values("overall", ascending=False)
        df.to_csv(RESULTS / f"summary_accuracy_{subset}.csv", index=False)
        (RESULTS / f"summary_accuracy_{subset}.md").write_text(df.to_markdown(index=False))
        print(f"\nAccuracy ({subset} academic pages)\n{df.to_markdown(index=False)}")

# Speed: per-page timings recorded during the accuracy runs.
rows = []
for csv in sorted(RESULTS.glob("timing_accuracy_*.csv")):
    tag = csv.stem.removeprefix("timing_accuracy_")
    t = pd.read_csv(csv)
    t = t[t.ok]
    meta = json.loads((RESULTS / f"meta_accuracy_{tag}.json").read_text())
    tool, mode, device = split_tag(tag)
    q1, med, q3 = np.percentile(t.seconds, [25, 50, 75])
    rows.append({"tool": tool, "mode": mode, "device": device, "pages": len(t),
                 "s_per_page_median": round(med, 2), "s_per_page_IQR": f"{q1:.2f}-{q3:.2f}",
                 "pages_per_min": round(60 / t.seconds.mean(), 1), "load_s": meta["load_seconds"]})
if rows:
    df = pd.DataFrame(rows).sort_values(["tool", "mode"])
    df.to_csv(RESULTS / "summary_speed.csv", index=False)
    (RESULTS / "summary_speed.md").write_text(df.to_markdown(index=False))
    print(f"\nSpeed\n{df.to_markdown(index=False)}")
