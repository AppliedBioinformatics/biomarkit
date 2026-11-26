# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""
Pick OmniDocBench's academic-literature pages, download their images, and write the page lists.

    uv run evals/parser_benchmark/select_pages.py

Writes to data/: OmniDocBench_academic.json (GT for the scorer), pages_academic.txt (all academic pages) and images/.
"""
import json
import urllib.parse
import urllib.request
from pathlib import Path

REVISION = "aa1ee96d106dbe53d0ae59474d75c6e6d9b53fec"
BASE = f"https://huggingface.co/datasets/opendatalab/OmniDocBench/resolve/{REVISION}"
DATA = Path(__file__).parent / "data"

gt_path = DATA / "OmniDocBench.json"
if not gt_path.exists():
    urllib.request.urlretrieve(f"{BASE}/OmniDocBench.json", gt_path)
pages = [p for p in json.loads(gt_path.read_text(encoding="utf-8"))
         if p["page_info"]["page_attribute"].get("data_source") == "academic_literature"]
(DATA / "OmniDocBench_academic.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
names = [p["page_info"]["image_path"] for p in pages]
(DATA / "pages_academic.txt").write_text("\n".join(names) + "\n")

images = DATA / "images"
images.mkdir(exist_ok=True)
for name in names:
    if not (images / name).exists():
        urllib.request.urlretrieve(f"{BASE}/images/{urllib.parse.quote(name)}", images / name)
print(f"{len(names)} academic pages ({sum(p['page_info']['page_attribute'].get('language') == 'english' for p in pages)} "
      f"English), images in {images}")
