# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Score prediction folders with OmniDocBench's end-to-end scorer (all and English pages) into results/scores/.

    uv run evals/parser_benchmark/score.py preds/accuracy/mineru_standard_cuda [more folders...]
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
VENDOR = ROOT / "vendor" / "OmniDocBench"
PYTHON = ROOT / ".venv-omnidocbench" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
GT = ROOT / "data" / "OmniDocBench_academic.json"
WORKERS = 8

parser = argparse.ArgumentParser()
parser.add_argument("preds", nargs="+", type=Path)
parser.add_argument("--gt", type=Path, default=GT, help="e.g. evals/fullpaper_benchmark/gt/omnidocbench.json")
args = parser.parse_args()

gt_pages = json.loads(args.gt.read_text(encoding="utf-8"))
subsets = (("all", None), ("english", {"language": "english"})) if args.gt == GT else (("all", None),)
for pred in args.preds:
    pred = (ROOT / pred).resolve() if not pred.is_absolute() else pred
    have = {p.stem for p in pred.glob("*.md")}
    pages = [p for p in gt_pages if Path(p["page_info"]["image_path"]).stem in have]
    if len(pages) < len(gt_pages):
        print(f"WARNING {pred.name}: predictions for {len(pages)}/{len(gt_pages)} pages - scoring those only")
    gt_subset = ROOT / "results" / "scores" / pred.name / "gt_subset.json"
    gt_subset.parent.mkdir(parents=True, exist_ok=True)
    gt_subset.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")

    for label, flt in subsets:
        dataset = {"dataset_name": "end2end_dataset", "ground_truth": {"data_path": str(gt_subset)},
                   "prediction": {"data_path": str(pred)}, "match_method": "quick_match",
                   "match_workers": WORKERS, "quick_match_truncated_timeout_sec": 300,
                   "match_timeout_sec": 420, "timeout_fallback_max_chunk_span": 10,
                   "timeout_fallback_order_penalty": 0.10}
        if flt:
            dataset["filter"] = flt
        cfg = {"end2end_eval": {"metrics": {"text_block": {"metric": ["Edit_dist"]},
                                            "display_formula": {"metric": ["Edit_dist"]},
                                            "table": {"metric": ["TEDS", "Edit_dist"], "teds_workers": WORKERS},
                                            "reading_order": {"metric": ["Edit_dist"]}},
                                "dataset": dataset}}
        cfg_path = gt_subset.parent / f"config_{label}.yaml"
        cfg_path.write_text(json.dumps(cfg, indent=2))  # JSON is valid YAML

        result_dir = VENDOR / "result"
        before = set(result_dir.glob("*")) if result_dir.exists() else set()
        # -X utf8: the scorer prints CJK brackets, which Windows' cp1252 console encoding can't encode.
        subprocess.run([str(PYTHON), "-X", "utf8", "pdf_validation.py", "--config", str(cfg_path)], cwd=VENDOR,
                       check=True)
        out = gt_subset.parent / label
        out.mkdir(exist_ok=True)
        for f in (VENDOR / "result").glob(f"{pred.name}_quick_match*"):
            if f not in before or f.stat().st_mtime > cfg_path.stat().st_mtime:
                shutil.move(str(f), out / f.name)
        print(f"{pred.name} [{label}] -> {out}")
