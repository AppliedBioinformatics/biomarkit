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
from text_download.basemodels.publication import Publication
from text_transformation.converters.ABC.transformer import Transformer
from text_transformation.utils.generics import check_mineru, MINERU_BACKEND_CHOICES

# OCR language passed to MinerU via -l. The CLI defaults to Chinese ("ch").
MINERU_OCR_LANG = "en"

# Parse subdirectory MinerU nests output under, per backend:
# pipeline backends use "auto", vlm backends use "vlm".
MINERU_PARSE_DIR = {"local-gpu": "auto", "local-cpu": "auto", "vllm": "vlm"}


class MinerUPdfTransformer(Transformer):
    """
    Converts PDF publications to .md format using the MinerU CLI (OpenDataLab).

    All pending PDFs are converted in a single MinerU invocation (or in
    sequential chunks when batch_size is set) so the models are loaded onto
    the GPU once per chunk rather than once per PDF. convert() then collects
    each publication's output; iteration, caching, and error handling are
    inherited from Converter.

    Inference runs locally by default (pipeline backend). With
    mineru_backend="vllm" the CLI acts as a thin client (vlm-http-client
    backend) and delegates inference to the remote vLLM server configured via
    MINERU_VLLM_ENDPOINT / MINERU_API_KEY in secrets.env.

    Attributes
    ----------
    output_dir : Path - RAW_MARKDOWN_DIR; MinerU writes <stem>/<parse_dir>/<stem>.md inside here.
    mineru_backend : str - "local-gpu", "local-cpu", or "vllm"; selects the MinerU backend.
    batch_size : int | None - Number of PDFs per MinerU call. Defaults to 25. None sends all at once.
    """

    def __init__(
        self,
        publication_list: List[Publication],
        mineru_backend: str = "local-gpu",
        batch_size: int = 25,
    ):
        super().__init__(publication_list)
        if mineru_backend not in MINERU_BACKEND_CHOICES:
            raise ValueError(
                f"Invalid mineru_backend: {mineru_backend!r}. "
                f"Allowed values: {', '.join(MINERU_BACKEND_CHOICES)}."
            )
        if batch_size is not None and batch_size < 1:
            raise ValueError(f"batch_size must be a positive integer, got {batch_size!r}.")
        
        self.mineru_backend = mineru_backend
        self.batch_size = batch_size

    def transform_all(self) -> None:
        """
        Overrides base class transform_all() to resolve the MinerU executable
        and run MinerU in sequential chunks before the collection loop.

        When batch_size is None all pending PDFs are sent in a single call.
        When batch_size is set the pending list is split into chunks of that
        size and each chunk is converted sequentially, so completed chunks are
        already cached on disk if a later chunk fails.
        """
        self._mineru_exe = check_mineru()
        if self.publication_list:
            pending = [pub for pub in self.publication_list if not self._build_output_path(pub).exists()]
            chunk_size = self.batch_size if self.batch_size is not None else len(pending)
            chunks = [pending[i:i + chunk_size] for i in range(0, max(len(pending), 1), chunk_size)]
            total_chunks = len(chunks)
            for idx, chunk in enumerate(chunks, start=1):
                if chunk:
                    logging.info(f"MinerU batch chunk {idx}/{total_chunks} ({len(chunk)} PDF(s)).")
                    self._run_mineru_batch(chunk)
        super().transform_all()

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
        if self.mineru_backend == "vllm":
            cmd += ["-b", "vlm-http-client", "-u", MINERU_VLLM_ENDPOINT]
        elif self.mineru_backend == "local-cpu":
            cmd += ["-b", "pipeline", "-l", MINERU_OCR_LANG]
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

        if self.mineru_backend == "vllm":
            env["MINERU_VL_API_KEY"] = MINERU_API_KEY
        elif self.mineru_backend == "local-cpu":
            env["CUDA_VISIBLE_DEVICES"] = ""
        return env

    def _run_mineru_batch(self, publications: List[Publication]) -> None:
        """
        Stages the given PDFs into a temporary directory and converts them with
        one MinerU CLI call. Passing a directory to -p makes MinerU load its
        models once and batch pages across documents.

        A non-zero exit is logged but not raised: MinerU may have converted a
        subset of the batch, and transform2json() checks each output individually.

        Parameters
        ----------
        publications : List[Publication] - Publications to stage and convert.
            Callers are responsible for filtering out already-converted files.
        """
        if not publications:
            return

        env = self._build_batch_env()

        with tempfile.TemporaryDirectory(prefix="mineru_batch_") as staging:
            staging_dir = Path(staging)
            for pub in publications:
                shutil.copy2(pub.publication_filepath, staging_dir / pub.publication_filepath.name)

            logging.info(f"MinerU batch starting: {len(publications)} PDF(s), endpoint={self.mineru_backend}.")
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
        Returns the path to the content_list_v2.json file MinerU produces.
        MinerU creates: output_dir/<stem>/<parse_dir>/<stem>_content_list_v2.json, where
        <parse_dir> is "auto" for the pipeline backend and "vlm" for the remote vLLM backend.

        Parameters
        ----------
        pub : Publication - Must have publication_filepath set.

        Returns
        -------
        Path - Path to the content_list_v2.json file produced by MinerU.
        """
        stem = pub.publication_filepath.stem
        return self.output_dir / stem / MINERU_PARSE_DIR[self.mineru_backend] / f"{stem}_content_list_v2.json"

    def transform2json(self, pub: Publication) -> Path | None:
        """
        Collects the content_list_v2.json produced for one publication by the batched
        MinerU run in convert_all().

        Parameters
        ----------
        pub : Publication - Must have publication_filepath set to a .pdf file.

        Returns
        -------
        Path - Path to the content_list_v2.json file, or None if MinerU produced no output for it.
        """
        json_path = self._build_output_path(pub)
        if not json_path.exists():
            logging.warning(f"MinerU produced no content_list_v2.json for {pub.doi} at {json_path}.")
            return None

        logging.info(f"MinerU converted {pub.doi} → {json_path}")
        return json_path