"""
Render the full-paper benchmark with standardise_text()'s default keep_ options (token reduction, Section 4).

    uv run python evals/fullpaper_benchmark/run_defaults.py   # biomarkit environment; run run_flags.py first

Reuses run_flags.py's cached conversions and writes ../parser_benchmark/preds/flags/<pdf|bioc>/defaults/<id>.md.
normalise_imrad is off (it needs an LLM and only renames headings).
"""
import inspect

import pandas as pd

import biomarkit as bmk
from biomarkit.config import get_corpus
from biomarkit.standardisation.text_cleaning.cleaner import Cleaner
from biomarkit.text_transformation.converters.bioc2json import BioCXmlTransformer
from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
from run_flags import OUT, ROOT, publication

DEFAULTS = {k: p.default for k, p in inspect.signature(bmk.standardise_text).parameters.items()
            if k.startswith("keep_")}

if __name__ == "__main__":
    bmk.load_corpus(ROOT / "corpus")
    manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
    selected = manifest[manifest.selected == "yes"]
    routes = {"pdf": {}, "bioc": {}}
    for r in selected.itertuples():
        pdf = ROOT / "pdfs" / ("manual" if r.pdf_source == "manual" else "") / f"{r.id}.pdf"
        routes["pdf"][r.id] = publication(r, pdf)
        routes["bioc"][r.id] = publication(r, get_corpus().download_dir / f"bioc_{r.id}.xml")
    MinerUPdfTransformer(publication_list=list(routes["pdf"].values()), mineru_tier="standard").transform_all()
    BioCXmlTransformer(publication_list=list(routes["bioc"].values())).transform_all()

    cleaner = Cleaner([], {**DEFAULTS, "normalise_imrad": False}, cache=None)
    for route, pubs in routes.items():
        out = OUT / route / "defaults"
        out.mkdir(parents=True, exist_ok=True)
        for i, p in pubs.items():
            if p.content_json_filepath:
                (out / f"{i}.md").write_text(cleaner.clean_from_json(p), encoding="utf-8")
        print(f"{route}: {len(list(out.glob('*.md')))} papers rendered with {DEFAULTS}")
