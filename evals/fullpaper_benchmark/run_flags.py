"""
Render the full-paper benchmark through biomarkit's keep_ filters (figures, tables, references, boilerplate and
inline LaTeX).

    uv run python evals/fullpaper_benchmark/run_flags.py   # biomarkit environment

Converts each selected paper twice (publisher PDF via MinerU, BioC XML via BioCXmlTransformer) and writes one
Markdown file per condition to ../parser_benchmark/preds/flags/<pdf|bioc>/<condition>/<id>.md.
"""
import json
import shutil
from pathlib import Path

import pandas as pd

import biomarkit as bmk
from biomarkit.config import get_corpus
from biomarkit.standardisation.text_cleaning.cleaner import Cleaner
from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_download.database.database import create_database
from biomarkit.text_transformation.converters.bioc2json import BioCXmlTransformer
from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

ROOT = Path(__file__).parent
OUT = ROOT.parent / "parser_benchmark" / "preds" / "flags"
# Every option is kept unless a condition sets it to False, so each condition changes only the options it names.
FIXED = {"keep_boilerplate": True, "keep_inline_latex": True, "keep_display_latex": True, "normalise_imrad": False}
CONDITIONS = {
    "all_kept": dict(keep_figures=True, keep_tables=True, keep_references=True),
    "no_figures": dict(keep_figures=False, keep_tables=True, keep_references=True),
    "no_tables": dict(keep_figures=True, keep_tables=False, keep_references=True),
    "no_references": dict(keep_figures=True, keep_tables=True, keep_references=False),
    "no_all3": dict(keep_figures=False, keep_tables=False, keep_references=False),
    "no_boilerplate": dict(keep_figures=True, keep_tables=True, keep_references=True, keep_boilerplate=False),
    "no_inline_latex": dict(keep_figures=True, keep_tables=True, keep_references=True, keep_inline_latex=False),
}


def publication(r, path: Path) -> Publication:
    gt = json.loads((ROOT / "gt" / f"{r.id}.json").read_text(encoding="utf-8"))
    title = next((b["text"] for b in gt["blocks"] if b["kind"] == "title"), r.doi)
    return Publication(doi=r.doi, title=title, publisher=r.publisher, year=int(gt.get("year") or 2000),
                       publication_filepath=path)


if __name__ == "__main__":
    bmk.load_corpus(ROOT / "corpus", build=True)
    create_database(get_corpus().db)
    manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
    selected = manifest[manifest.selected == "yes"]

    bioc_dir = get_corpus().download_dir
    bioc_dir.mkdir(parents=True, exist_ok=True)
    routes = {"pdf": {}, "bioc": {}}
    for r in selected.itertuples():
        pdf = ROOT / "pdfs" / ("manual" if r.pdf_source == "manual" else "") / f"{r.id}.pdf"
        routes["pdf"][r.id] = publication(r, pdf)
        xml = bioc_dir / f"bioc_{r.id}.xml"  # BioC files are recognised by this prefix
        shutil.copy(ROOT / "gt" / "raw" / f"{r.id}.xml", xml)
        routes["bioc"][r.id] = publication(r, xml)

    MinerUPdfTransformer(publication_list=list(routes["pdf"].values()), mineru_tier="standard").transform_all()
    BioCXmlTransformer(publication_list=list(routes["bioc"].values())).transform_all()

    for route, pubs in routes.items():
        missing = [i for i, p in pubs.items() if p.content_json_filepath is None]
        if missing:
            print(f"{route}: no JSON for {missing}")
        for name, flags in CONDITIONS.items():
            cleaner = Cleaner([], {**FIXED, **flags}, cache=None)
            out = OUT / route / name
            out.mkdir(parents=True, exist_ok=True)
            for i, p in pubs.items():
                if p.content_json_filepath:
                    (out / f"{i}.md").write_text(cleaner.clean_from_json(p), encoding="utf-8")
        done = sum(p.content_json_filepath is not None for p in pubs.values())
        print(f"{route}: {done} papers x {len(CONDITIONS)} conditions")
