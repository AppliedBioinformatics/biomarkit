# /// script
# requires-python = ">=3.11"
# dependencies = ["pandas==3.1.1", "requests"]
# ///
"""
Download full PMC JATS XML for the selected full-paper benchmark articles to gt/jats/<id>.xml.

    uv run evals/fullpaper_benchmark/fetch_jats.py

Tries Europe PMC fullTextXML first, then PMC's OAI-PMH service (fetched with curl: NCBI rejects Python clients). PMC
copies carry the JATS namespace, Europe PMC copies do not. Articles without a PMCID are looked up by DOI.
"""
import re
import subprocess
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent
OUT = ROOT / "gt" / "jats"
EUROPEPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/{}/fullTextXML"
PMC_OAI = ("https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:{}"
           "&metadataPrefix=pmc")


def pmcid_for(doi: str) -> str:
    try:
        r = requests.get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                         params={"query": f'DOI:"{doi}"', "format": "json"}, timeout=60)
        return next((h["pmcid"] for h in r.json()["resultList"]["result"] if h.get("pmcid")), "")
    except (requests.RequestException, ValueError, KeyError):
        return ""


def europepmc(pmcid: str) -> str | None:
    for _ in range(3):  # Europe PMC often times out or returns 5xx
        try:
            r = requests.get(EUROPEPMC.format(pmcid), timeout=60)
            if r.ok and "<article" in r.text:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(5)
    return None


def pmc_oai(pmcid: str) -> str | None:
    out = subprocess.run(["curl", "-s", "--max-time", "90", PMC_OAI.format(pmcid.removeprefix("PMC"))],
                         capture_output=True, text=True, encoding="utf-8").stdout
    article = re.search(r"<article[\s>].*</article>", out, re.S)
    return article.group(0) if article else None


OUT.mkdir(parents=True, exist_ok=True)
manifest = pd.read_csv(ROOT / "manifest.csv", dtype=str).fillna("")
selected = manifest[manifest.selected == "yes"]
missing = []
for r in selected.itertuples():
    path = OUT / f"{r.id}.xml"
    if path.exists():
        continue
    pmcid = r.pmcid if r.pmcid not in ("", "PMC") else pmcid_for(r.doi)
    text = (europepmc(pmcid) or pmc_oai(pmcid)) if pmcid else None
    if text:
        path.write_text(text, encoding="utf-8")
    else:
        missing.append(r.id)
print(f"{len(selected) - len(missing)}/{len(selected)} JATS files in {OUT}; missing: {missing}")
