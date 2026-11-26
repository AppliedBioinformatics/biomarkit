# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["docling==2.151.1", "easyocr", "torch==2.9.1", "torchvision==0.24.1"]
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
Docling 2.151.1 standard pipeline (layout + OCR + TableFormer, with formula enrichment so equations come out as LaTeX
rather than images) on the OmniDocBench academic pages.

    uv run evals/parser_benchmark/run_docling.py --mode standard
"""
import sys
from importlib.metadata import version
from pathlib import Path

from common import parse_args, run

args = parse_args(["standard"])


def load():
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import EasyOcrOptions, PdfPipelineOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption

    # EasyOCR, not the auto choice (RapidOCR), whose models download from modelscope.cn and fail here.
    opts = PdfPipelineOptions(do_ocr=True, ocr_options=EasyOcrOptions(), do_table_structure=True,
                              do_formula_enrichment=True,
                              accelerator_options=AcceleratorOptions(device=AcceleratorDevice.CUDA))
    return DocumentConverter(format_options={InputFormat.IMAGE: ImageFormatOption(pipeline_options=opts)})


def convert(converter, image: Path):
    return converter.convert(image).document.export_to_markdown()


if __name__ == "__main__":
    sys.exit(run("docling", version("docling"), args, load, convert))