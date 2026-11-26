# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas"]
# ///
"""
Sample candidate papers for the full-paper benchmark from BioC XMLs already downloaded into the corpora.

    uv run evals/fullpaper_benchmark/select_papers.py

Candidates per publisher are drawn round-robin across journals (journal code taken from the DOI suffix) with a fixed
seed, so each journal contributes one paper before any contributes a second. The 100 DOIs of the original annotation set (evals/eval2doi.py) are excluded.
Writes manifest.csv and copies each BioC XML to gt/raw/<id>.xml.
"""
import ast
import random
import re
import shutil
from collections import defaultdict
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent
REPO = ROOT.parents[1]
CORPORA = {"Q1": "wheat_rust", "Q2": "ras_cancer", "Q3": "climate_change"}
# Candidates drawn per publisher (targets after attrition: 20 Wiley, 10 others).
# Wiley layouts vary far more between journals than Springer's do, so it gets a larger sample.
# Extra Wiley/Frontiers candidates replace structure exclusions (wiley_08, wiley_31, frontiers_14); earlier ids are unchanged.
N_CANDIDATES = {"wiley": 32, "elsevier": 15, "springer": 15, "frontiers": 16, "mdpi": 15, "plos": 15}


def journal_code(doi: str) -> str:
    """Journal proxy from the DOI suffix: 10.1111/mec.123 -> mec, 10.1016/j.funbio.1 -> funbio,
    10.1007/s00122-020-1 -> s00122, 10.3390/cimb46010045 -> cimb, 10.1371/journal.pone.1 -> pone."""
    suffix = doi.lower().split("/", 1)[1]
    suffix = re.sub(r"^(j|journal)\.", "", suffix)
    token = re.split(r"[.\-_/]", suffix)[0]
    if re.fullmatch(r"s?\d+", token):  # Springer journal IDs (s00122), Wiley ISSN-style DOIs (1365-2745)
        return token
    return re.sub(r"^\d+|\d+$", "", token)  # MDPI trailing volume digits, AGU leading year (2021MS -> ms)


excluded = {doi.lower() for pub in ast.literal_eval((REPO / "evals" / "eval2doi.py").read_text().split("=", 1)[1]).values()
            for doi in pub.values()}

rows = []
for query, corpus in CORPORA.items():
    cdir = REPO / "biomarkit" / "corpora" / corpus
    df = pd.read_csv(cdir / "reports" / "benchmark_per_doi.csv")
    df = df[df.success & df.file.str.startswith("bioc_", na=False) & df.publisher.isin(N_CANDIDATES.keys())]
    for r in df.itertuples():
        if r.doi.lower() not in excluded:
            rows.append({"doi": r.doi, "publisher": r.publisher, "query": query, "journal": journal_code(r.doi),
                         "bioc_source": str(cdir / "manuscripts" / r.file)})
pool = pd.DataFrame(rows).drop_duplicates("doi")

rng = random.Random(0)
picked = []
for publisher, n in N_CANDIDATES.items():
    by_journal = defaultdict(list)
    for r in pool[pool.publisher == publisher].to_dict("records"):
        by_journal[r["journal"]].append(r)
    journals = sorted(by_journal)
    rng.shuffle(journals)
    for j in journals:
        rng.shuffle(by_journal[j])
    chosen, round_ = [], 0
    while len(chosen) < n and any(len(v) > round_ for v in by_journal.values()):
        for j in journals:
            if len(chosen) < n and len(by_journal[j]) > round_:
                chosen.append(by_journal[j][round_])
        round_ += 1
    for i, r in enumerate(chosen, 1):
        r["id"] = f"{publisher}_{i:02d}"
    picked += chosen
    print(f"{publisher}: {len(chosen)}/{n} candidates from {len({r['journal'] for r in chosen})} journals "
          f"(pool {sum(len(v) for v in by_journal.values())} papers, {len(journals)} journals)")

manifest = pd.DataFrame(picked)[["id", "doi", "publisher", "journal", "query", "bioc_source"]]
for col in ("pmcid", "pdf_source", "status", "reason"):
    manifest[col] = ""
raw = ROOT / "gt" / "raw"
raw.mkdir(parents=True, exist_ok=True)
for r in manifest.itertuples():
    shutil.copy(r.bioc_source, raw / f"{r.id}.xml")
manifest.to_csv(ROOT / "manifest.csv", index=False)
print(f"\n{len(manifest)} candidates -> {ROOT / 'manifest.csv'}")
