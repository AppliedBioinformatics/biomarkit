"""
Convert PDF publications to .md format using the MinerU CLI (OpenDataLab).
Provides the MinerUPdfConverter class for use within the text-transformation pipeline.
"""
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List

from config import MINERU_VIRTUAL_VRAM_SIZE, MINERU_VLLM_ENDPOINT, MINERU_API_KEY
from text_extraction.basemodels.publication import Publication
from text_transformation.converters.ABC.converter import Converter
from text_transformation.utils.generics import check_mineru, MINERU_ENDPOINT_CHOICES

# OCR language passed to MinerU via -l. The CLI defaults to Chinese ("ch").
MINERU_OCR_LANG = "en"

# Parse subdirectory MinerU nests output under, per backend:
# pipeline uses the parse method ("auto"), vlm backends use "vlm".
MINERU_PARSE_DIR = {"local": "auto", "vllm": "vlm"}


class MinerUPdfConverter(Converter):
    """
    Converts PDF publications to .md format using the MinerU CLI (OpenDataLab).

    All pending PDFs are converted in a single MinerU invocation so the models
    are loaded onto the GPU once per run rather than once per PDF. convert()
    then collects each publication's output; iteration, caching, and error
    handling are inherited from Converter.

    Inference runs locally by default (pipeline backend). With
    mineru_endpoint="vllm" the CLI acts as a thin client (vlm-http-client
    backend) and delegates inference to the remote vLLM server configured via
    MINERU_VLLM_ENDPOINT / MINERU_API_KEY in secrets.env.

    Attributes
    ----------
    output_dir : Path - RAW_MARKDOWN_DIR; MinerU writes <stem>/<parse_dir>/<stem>.md inside here.
    mineru_endpoint : str - "local" or "vllm"; selects the MinerU backend.
    """

    def __init__(self, publication_list: List[Publication], mineru_endpoint: str = "local"):
        super().__init__(publication_list)
        if mineru_endpoint not in MINERU_ENDPOINT_CHOICES:
            raise ValueError(
                f"Invalid mineru_endpoint: {mineru_endpoint!r}. "
                f"Allowed values: {', '.join(MINERU_ENDPOINT_CHOICES)}."
            )
        self.mineru_endpoint = mineru_endpoint

    def convert_all(self) -> None:
        """
        Overrides base class convert_all() to resolve the MinerU executable and
        run the single batched MinerU invocation before entering the collection
        loop, which verifies and caches each publication's output via convert().
        """
        self._mineru_exe = check_mineru()
        if self.publication_list:
            self._run_mineru_batch()
        super().convert_all()

    def _build_batch_command(self, staging_dir: Path) -> list[str]:
        """
        Builds the MinerU CLI argument list for the batch run.

        Local mode uses the pipeline backend with English OCR. vllm mode uses
        the vlm-http-client backend, pointing -u at the remote server; OCR
        language does not apply to the VLM backend so -l is omitted.

        Parameters
        ----------
        staging_dir : Path - Directory holding the staged PDFs.

        Returns
        -------
        list[str] - Full command to pass to subprocess.run.
        """
        cmd = [str(self._mineru_exe), "-p", str(staging_dir), "-o", str(self.output_dir)]
        if self.mineru_endpoint == "vllm":
            cmd += ["-b", "vlm-http-client", "-u", MINERU_VLLM_ENDPOINT]
        else:
            cmd += ["-b", "pipeline", "-l", MINERU_OCR_LANG]
        return cmd

    def _build_batch_env(self) -> dict:
        """
        Builds the environment for the MinerU subprocess.

        In vllm mode the API key is exposed as MINERU_VL_API_KEY, which
        MinerU's HTTP client sends as a Bearer Authorization header.

        Returns
        -------
        dict - Environment mapping for subprocess.run.
        """
        env = os.environ.copy()
        if MINERU_VIRTUAL_VRAM_SIZE:
            env["MINERU_VIRTUAL_VRAM_SIZE"] = MINERU_VIRTUAL_VRAM_SIZE
        else:
            # A blank value in secrets.env leaks into os.environ as "" — drop it
            # so MinerU auto-detects instead of warning about an invalid integer.
            env.pop("MINERU_VIRTUAL_VRAM_SIZE", None)

        if self.mineru_endpoint == "vllm":
            env["MINERU_VL_API_KEY"] = MINERU_API_KEY
        return env

    def _run_mineru_batch(self) -> None:
        """
        Stages all pending PDFs into a temporary directory and converts them
        with one MinerU CLI call. Passing a directory to -p makes MinerU load
        its models once and batch pages across documents, instead of paying the
        model-load cost per PDF.

        Publications whose output .md already exists on disk (e.g. converted by
        a previous run that was interrupted before the cache was written) are
        not re-staged; convert() picks their files up and caches them as normal.

        A non-zero exit is logged but not raised: MinerU may have converted a
        subset of the batch, and convert() checks each output individually.
        """
        pending = [pub for pub in self.publication_list if not self._build_output_path(pub).exists()]
        recovered = len(self.publication_list) - len(pending)
        if recovered:
            logging.info(
                f"{recovered} publication(s) already have MinerU output on disk — "
                f"skipping reconversion; they will be cached from the existing files."
            )
        if not pending:
            return

        env = self._build_batch_env()

        with tempfile.TemporaryDirectory(prefix="mineru_batch_") as staging:
            staging_dir = Path(staging)
            for pub in pending:
                shutil.copy2(pub.publication_filepath, staging_dir / pub.publication_filepath.name)

            logging.info(f"MinerU batch starting: {len(pending)} PDF(s), endpoint={self.mineru_endpoint}.")
            result = subprocess.run(
                self._build_batch_command(staging_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )

        if result.returncode != 0:
            logging.warning(
                f"MinerU batch exited with code {result.returncode} — some conversions may have "
                f"failed; each publication's output is verified individually. "
                f"stderr: {result.stderr.strip()}"
            )

    def _build_output_path(self, pub: Publication) -> Path:
        """
        Returns the path MinerU writes the markdown file to.
        MinerU creates: output_dir/<stem>/<parse_dir>/<stem>.md, where
        <parse_dir> is "auto" for the pipeline backend and "vlm" for the
        remote vLLM backend.

        Parameters
        ----------
        pub : Publication - Must have publication_filepath set.

        Returns
        -------
        Path - Path to the .md file produced by MinerU.
        """
        stem = pub.publication_filepath.stem
        return self.output_dir / stem / MINERU_PARSE_DIR[self.mineru_endpoint] / f"{stem}.md"

    def convert(self, pub: Publication) -> Path | None:
        """
        Collects the markdown produced for one publication by the batched
        MinerU run in convert_all().

        Parameters
        ----------
        pub : Publication - Must have publication_filepath set to a .pdf file.

        Returns
        -------
        Path - Path to the .md file, or None if MinerU produced no output for it.
        """
        md_path = self._build_output_path(pub)
        if not md_path.exists():
            logging.warning(f"MinerU produced no .md file for {pub.doi} at {md_path}.")
            return None

        logging.info(f"MinerU converted {pub.doi} → {md_path}")
        return md_path