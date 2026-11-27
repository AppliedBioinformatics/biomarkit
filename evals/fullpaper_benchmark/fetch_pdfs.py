"""
Download publisher PDFs for the full-paper candidates; failures are listed in manual_downloads.csv.

    uv run python evals/fullpaper_benchmark/fetch_pdfs.py   # biomarkit environment
"""
import json
import shutil
from pathlib import Path

import pandas as pd
import requests

import biomarkit as bmk
from biomarkit.config import ELSEVIER_API_KEY, get_corpus
from biomarkit.text_download.apis.map import api_clients
from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_download.database.database import create_database

ROOT = Path(__file__).parent
PDFS = ROOT / "pdfs"
PLOS_SLUGS = {"pone": "plosone", "pgen": "plosgenetics", "pbio": "plosbiology", "pntd": "plosntds",
              "pcbi": "ploscompbiol", "ppat": "plospathogens", "pmed": "plosmedicine"}


# Helpers
def is_pdf(path):
    return path is not None and Path(path).is_file() and Path(path).read_bytes()[:4] == b"%PDF"


def has_pdf(i):
    return is_pdf(PDFS / f"{i}.pdf") or is_pdf(PDFS / "manual" / f"{i}.pdf")


def save_response(url, out, **kwargs):
    try:
        resp = requests.get(url, timeout=60, **kwargs)
        resp.raise_for_status()
        if resp.content[:4] == b"%PDF":
            out.write_bytes(resp.content)
    except requests.RequestException as e:
        print(f"{out.stem}: {e}")

# SetUp biomarkit corpus.
manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
manifest = manifest[manifest.status != "excluded"]
todo = manifest[~manifest.id.map(has_pdf)]
(PDFS / "manual").mkdir(parents=True, exist_ok=True)

bmk.load_corpus(ROOT / "corpus", build=True)
create_database(get_corpus().db)  # normally created by the pipeline

# Download and save PDFs, skip opensource client to obtain PDFs directly from journal publishers.
for publisher in ("springer", "wiley", "mdpi", "frontiers"):
    rows = todo[todo.publisher == publisher]
    if rows.empty:
        continue
    pubs = {}
    for r in rows.itertuples():
        gt = json.loads((ROOT / "gt" / f"{r.id}.json").read_text(encoding="utf-8"))
        title = next((b["text"] for b in gt["blocks"] if b["kind"] == "title"), r.doi)
        pubs[r.id] = Publication(doi=r.doi, title=title, publisher=publisher, year=int(gt.get("year") or 2000))
    api_clients[publisher](publication_list=list(pubs.values())).download_all_papers()
    for i, p in pubs.items():
        if is_pdf(p.publication_filepath):
            shutil.copy(p.publication_filepath, PDFS / f"{i}.pdf")

# Custom PDF download required for elsevier (biomarkit usually uses PDF)
for r in todo[todo.publisher == "elsevier"].itertuples():
    save_response(f"https://api.elsevier.com/content/article/doi/{r.doi}", PDFS / f"{r.id}.pdf",
                  headers={"X-ELS-APIKey": ELSEVIER_API_KEY, "Accept": "application/pdf"})

# Same for PloS
for r in todo[todo.publisher == "plos"].itertuples():
    save_response(f"https://journals.plos.org/{PLOS_SLUGS.get(r.journal, 'plosone')}/article/file?id={r.doi}&type=printable",
                  PDFS / f"{r.id}.pdf")

# Check missing downloads and save a CSV file to get them manually if required.
missing = manifest[~manifest.id.map(has_pdf)]
missing[["id", "doi", "publisher", "pmcid"]].assign(
    publisher_url="https://doi.org/" + missing.doi,
    pmc_url="https://pmc.ncbi.nlm.nih.gov/articles/" + missing.pmcid + "/",
    save_as=(PDFS / "manual").as_posix() + "/" + missing.id + ".pdf").to_csv(ROOT / "manual_downloads.csv", index=False)
print(f"{len(manifest) - len(missing)} PDFs saved; {len(missing)} need manual download (manual_downloads.csv)")