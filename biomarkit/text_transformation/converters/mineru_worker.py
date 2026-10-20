"""
MinerU 4 worker process — converts one batch of PDFs to content_list_v2.json.

Run by MinerUPdfTransformer as ``python -m biomarkit.text_transformation.converters.mineru_worker <job.json>``.
Running MinerU in a separate process per batch loads its models once for the whole batch, isolates native
crashes (CUDA / llama.cpp) to that batch, and frees all GPU memory when the batch finishes.

The job file is JSON::

    {
        "tier": "standard",
        "server_url": "",            # optional remote VLM server
        "api_key": "",               # optional remote VLM API key
        "results": "<path>",         # where per-PDF results are written
        "cleanup": true,             # keep only the content list and images/
        "items": [{"pdf": "<path>", "out_dir": "<path>"}, ...]
    }

For each item the worker writes MinerU's saved result (middle_json.json, markdown.md, images/, ...) into out_dir,
then renders Content List V2 from the saved middle JSON to out_dir/<pdf stem>_content_list_v2.json. Rendering
from the saved copy means image paths in the content list point at the images/ folder next to it. With cleanup,
everything except the content list and images/ is then deleted.
"""
import json
import logging
import sys
import traceback
from pathlib import Path


def run_job(job: dict) -> list[dict]:
    """
    Converts every PDF in the job with a single MinerUParser, isolating failures per PDF.

    Parameters
    ----------
    job : dict - Parsed job file (see module docstring).

    Returns
    -------
    list[dict] - One {"pdf", "ok", "error"} record per item, in job order. Also written to job["results"].
    """
    from mineru.config import VlmConfig
    from mineru.parser import MinerUParser, ParseResult
    from mineru.parser.writer import FileBasedDataWriter
    from mineru.render import render_content_list_v2
    from biomarkit.text_transformation.utils.generics import prune_intermediate_dir

    vlm_config = None
    if job.get("server_url"):
        vlm_config = VlmConfig(server_url=job["server_url"], api_key=job.get("api_key") or "")

    parser = MinerUParser(tier=job["tier"], parse_mode="auto", vlm_config=vlm_config)

    results = []
    for item in job["items"]:
        pdf, out_dir = Path(item["pdf"]), Path(item["out_dir"])
        record = {"pdf": str(pdf), "ok": False, "error": None}
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            result = parser.parse(pdf, page_range="all")
            result.save(FileBasedDataWriter(str(out_dir)))

            saved = ParseResult.from_json((out_dir / "middle_json.json").read_text(encoding="utf-8"))
            content_list = render_content_list_v2(saved.middle_json)
            content_json_path = out_dir / f"{pdf.stem}_content_list_v2.json"
            content_json_path.write_text(json.dumps(content_list, ensure_ascii=False), encoding="utf-8")
            if job.get("cleanup"):
                # Drop MinerU's other outputs straight away (raw model output alone is ~6 MB per paper).
                prune_intermediate_dir(content_json_path)
            record["ok"] = True
        except Exception as e:
            record["error"] = f"{type(e).__name__}: {e}"
            logging.error(f"MinerU failed on {pdf}: {record['error']}\n{traceback.format_exc()}")
        results.append(record)

        # Rewritten after every PDF so results survive a native crash later in the batch.
        if job.get("results"):
            Path(job["results"]).write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results


def main(job_path: str) -> None:
    run_job(json.loads(Path(job_path).read_text(encoding="utf-8")))


# Required: MinerU's VLM tiers start child processes, and on Windows (spawn) each child re-imports
# __main__ — without this guard every child would re-run the whole job.
if __name__ == "__main__":
    main(sys.argv[1])
