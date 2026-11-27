# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["mineru[torch]==4.0.12", "docvortex==0.5.16", "torch==2.9.1", "torchvision==0.24.1"]
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
MinerU 4.0.12 (the version biomarkit ships) on the OmniDocBench pages.

    uv run evals/parser_benchmark/run_mineru.py --mode standard
"""
import os
import sys
from importlib.metadata import version

from common import parse_args, run

args = parse_args(["flash", "basic", "standard", "advanced"])
os.environ["MINERU_DEVICE_MODE"] = args.device  # read by MinerU at import/model load


def load():
    from mineru.parser import MinerUParser
    return MinerUParser(tier=args.mode, parse_mode="auto")


def convert(parser, image):
    return parser.parse(image, page_range="all").markdown()  # all pages when given a PDF


# Required on Windows: MinerU's VLM tiers spawn child processes that re-import __main__.
if __name__ == "__main__":
    sys.exit(run("mineru", version("mineru"), args, load, convert))
