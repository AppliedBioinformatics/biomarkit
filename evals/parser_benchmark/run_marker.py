# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["marker-pdf==2.2.0", "torch==2.9.1", "torchvision==0.24.1"]
#
# [tool.uv]
# index-strategy = "unsafe-best-match"
#
# [[tool.uv.index]]
# name = "pytorch-cu128"
# url = "https://download.pytorch.org/whl/cu128"
# explicit = true
#
# [tool.uv.sources]
# torch = [{ index = "pytorch-cu128" }]
# torchvision = [{ index = "pytorch-cu128" }]
# ///
"""
Marker 2.2.0 (LLM-assist off) on the OmniDocBench pages; VLM modes need llama-server in vendor/llama.cpp/.

    uv run evals/parser_benchmark/run_marker.py --mode balanced
"""
import os
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

# indra-ocr reads its model files without an encoding, which fails under Windows' cp1252 default.
if not sys.flags.utf8_mode:
    sys.exit(subprocess.call([sys.executable, "-X", "utf8", *sys.argv]))

from common import ROOT, parse_args, run

args = parse_args(["fast", "balanced", "accurate"])
os.environ["TORCH_DEVICE"] = args.device
os.environ.setdefault("SURYA_INFERENCE_BACKEND", "llamacpp")
llama_server = next((ROOT / "vendor" / "llama.cpp").rglob("llama-server.exe"), None) \
    if (ROOT / "vendor" / "llama.cpp").exists() else None
if llama_server:
    os.environ.setdefault("LLAMA_CPP_BINARY", str(llama_server))


def load():
    from marker.converters.pdf import PdfConverter
    from marker.config.parser import ConfigParser
    from marker.models import create_model_dict

    cfg = ConfigParser({"mode": args.mode, "output_format": "markdown", "disable_tqdm": True})
    models = create_model_dict(load_indra=args.mode != "accurate", no_server=args.mode == "fast")
    return PdfConverter(config=cfg.generate_config_dict(), artifact_dict=models,
                        processor_list=cfg.get_processors(), renderer=cfg.get_renderer())


def convert(converter, image: Path):
    from marker.output import text_from_rendered
    return text_from_rendered(converter(str(image)))[0]


if __name__ == "__main__":
    sys.exit(run("marker", version("marker-pdf"), args, load, convert))
