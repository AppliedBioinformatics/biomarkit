"""Shared run loop for the run_*.py scripts: page list, warm-up, per-page timing, timing CSV."""
import argparse
import csv
import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).parent
IMAGES = ROOT / "data" / "images"
# Inline base64 figures are replaced for every tool alike; OmniDocBench ignores figures.
_DATA_URI = re.compile(r"\]\(data:image/[^)]*\)")


def parse_args(modes: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", required=True, choices=modes)
    p.add_argument("--device", default="cuda", choices=["cuda"])
    p.add_argument("--pages", default="pages_academic.txt", help="Page list in data/ (see select_pages.py).")
    p.add_argument("--resume", action="store_true", help="Skip pages that already have a prediction (after a crash).")
    return p.parse_args()


def run(tool: str, version: str, args: argparse.Namespace, load, convert) -> None:
    """load() builds the model(s) once and returns a converter state; convert(state, image_path) returns Markdown."""
    pages = (ROOT / "data" / args.pages).read_text().split()
    # Other page lists (e.g. fullpaper.txt, absolute PDF paths) get their own output folder and tag prefix.
    kind = "accuracy" if args.pages == "pages_academic.txt" else Path(args.pages).stem
    tag = f"{tool}_{args.mode}_{args.device}" if kind == "accuracy" else f"{kind}_{tool}_{args.mode}_{args.device}"
    out_dir = ROOT / "preds" / kind / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    results = ROOT / "results"
    results.mkdir(exist_ok=True)
    if args.resume:  # skip pages that already have a prediction; timings are appended
        pages = [p for p in pages if not (out_dir / f"{Path(p).stem}.md").exists()]

    t0 = time.perf_counter()
    state = load()
    load_seconds = time.perf_counter() - t0
    convert(state, IMAGES / pages[0])  # warm-up, untimed

    rows = []
    for i, page in enumerate(pages, 1):
        t0, md, error = time.perf_counter(), "", None
        try:
            md = convert(state, IMAGES / page)
        except Exception as e:
            error = f"{type(e).__name__}: {e}"
        rows.append({"page": page, "seconds": round(time.perf_counter() - t0, 3), "ok": error is None, "error": error})
        (out_dir / f"{Path(page).stem}.md").write_text(_DATA_URI.sub("](image)", md), encoding="utf-8")
        if i % 20 == 0:
            print(f"[{tag}] {i}/{len(pages)}", flush=True)

    timing_path = results / f"timing_{kind}_{tag}.csv"
    append = args.resume and timing_path.exists()
    with open(timing_path, "a" if append else "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        if not append:
            w.writeheader()
        w.writerows(rows)

    meta = {"tool": tool, "version": version, "mode": args.mode, "device": args.device, "pages_file": args.pages,
            "n_pages": len(pages), "load_seconds": round(load_seconds, 2), "failures": sum(not r["ok"] for r in rows)}
    (results / f"meta_{kind}_{tag}.json").write_text(json.dumps(meta, indent=2))
    secs = [r["seconds"] for r in rows if r["ok"]]
    print(f"[{tag}] done: {len(pages)} pages, median {sorted(secs)[len(secs) // 2]:.2f} s/page, "
          f"{meta['failures']} failures" if secs else f"[{tag}] all pages failed")