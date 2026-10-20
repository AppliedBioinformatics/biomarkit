"""
Convert PDF publications to content_list_v2.json using MinerU 4 (OpenDataLab).
Provides the MinerUPdfTransformer class for use within the text-transformation pipeline.
"""
import json
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

from tqdm import tqdm

from biomarkit.config import MINERU_TIER_CHOICES, MINERU_VLM_SERVER_URL, MINERU_VLM_API_KEY
from biomarkit.text_download.basemodels.publication import Publication
from biomarkit.text_download.utils.generics import progress_split_bar
from biomarkit.text_transformation.converters.ABC.transformer import Transformer

# Legacy MinerU 3.x variables. MinerU 4 refuses to run if MINERU_VL_API_KEY conflicts with its own config,
# and ignores the others, so they are stripped from the worker's environment.
_LEGACY_MINERU_ENV = ("MINERU_VL_API_KEY", "MINERU_VL_MODEL_NAME", "MINERU_VIRTUAL_VRAM_SIZE", "MINERU_MODEL_STACK")


class MinerUPdfTransformer(Transformer):
    """
    Converts PDF publications to content_list_v2.json using MinerU 4 (OpenDataLab).

    Pending PDFs are converted in sequential chunks. Each chunk runs in its own worker process
    (mineru_worker.py), which loads MinerU's models once for the chunk, keeps a native crash from
    taking down the pipeline, and releases all GPU memory when the chunk ends. transform2json()
    then collects each publication's output; iteration, caching, and error handling are inherited
    from Transformer.

    The VLM tiers run MinerU's VLM locally by default. If MINERU_VLM_SERVER_URL is set in
    secrets.env, VLM inference is sent to that remote server instead.

    Attributes
    ----------
    output_dir : Path - The corpus intermediates folder; output goes to <stem>/auto/ inside it.
    mineru_tier : str - "basic", "standard", or "advanced"; the MinerU parsing tier.
    batch_size : int | None - Number of PDFs per worker process. Defaults to 25. None sends all at once.
    cleanup : bool - If True (default), the worker keeps only each PDF's content_list_v2.json and images/,
        deleting MinerU's other outputs as soon as each PDF is done.
    """

    def __init__(
        self,
        publication_list: List[Publication],
        mineru_tier: str = "standard",
        batch_size: int = 25,
        cleanup: bool = True,
    ):
        super().__init__(publication_list)
        if mineru_tier not in MINERU_TIER_CHOICES:
            raise ValueError(
                f"Invalid mineru_tier: {mineru_tier!r}. "
                f"Allowed values: {', '.join(MINERU_TIER_CHOICES)}."
            )
        if batch_size is not None and batch_size < 1:
            raise ValueError(f"batch_size must be a positive integer, got {batch_size!r}.")

        self.mineru_tier = mineru_tier
        self.batch_size = batch_size
        self.cleanup = cleanup

    def transform_all(self) -> None:
        """
        Overrides base class transform_all() to run MinerU in sequential chunks before the
        collection loop.

        When batch_size is None all pending PDFs are sent in a single chunk. When batch_size is
        set the pending list is split into chunks of that size and each chunk is converted
        sequentially, so completed chunks are already cached on disk if a later chunk fails.
        """
        if self.publication_list:
            pending = [pub for pub in self.publication_list if not self._build_output_path(pub).exists()]
            chunk_size = self.batch_size if self.batch_size is not None else len(pending)
            chunks = [pending[i:i + chunk_size] for i in range(0, max(len(pending), 1), chunk_size)]
            total_chunks = len(chunks)
            succeeded, failed = 0, 0
            with tqdm(enumerate(chunks, start=1), desc="MinerU batches", total=total_chunks,
                      unit="batch", leave=True, dynamic_ncols=True) as bar:
                for idx, chunk in bar:
                    if chunk:
                        logging.debug(f"MinerU batch chunk {idx}/{total_chunks} ({len(chunk)} PDF(s)).")
                        self._run_worker_batch(chunk)
                        self._cache_chunk(chunk)
                        chunk_ok = sum(1 for p in chunk if p.content_json_filepath is not None)
                        succeeded += chunk_ok
                        failed += len(chunk) - chunk_ok
                    bar.set_postfix_str(progress_split_bar(succeeded, failed, len(pending)))
        super().transform_all()

    def _build_job(self, publications: List[Publication], results_path: Path) -> dict:
        """
        Builds the worker job for one chunk of publications.

        Parameters
        ----------
        publications : List[Publication] - Publications to convert.
        results_path : Path - Where the worker writes its per-PDF results.

        Returns
        -------
        dict - Job description consumed by mineru_worker.run_job().
        """
        return {
            "tier": self.mineru_tier,
            "server_url": MINERU_VLM_SERVER_URL or "",
            "api_key": MINERU_VLM_API_KEY or "",
            "results": str(results_path),
            "cleanup": self.cleanup,
            "items": [
                {"pdf": str(pub.publication_filepath), "out_dir": str(self._build_output_path(pub).parent)}
                for pub in publications
            ],
        }

    @staticmethod
    def _build_worker_env() -> dict:
        """
        Builds the environment for the worker process: the current environment minus legacy
        MinerU 3.x variables (see _LEGACY_MINERU_ENV).

        Returns
        -------
        dict - Environment mapping for subprocess.run.
        """
        env = os.environ.copy()
        for name in _LEGACY_MINERU_ENV:
            env.pop(name, None)
        return env

    def _cache_chunk(self, publications: List[Publication]) -> None:
        """
        Writes content_json_filepath to the cache for each publication in a
        completed chunk, so progress survives if a later chunk fails or hangs.
        """
        for pub in publications:
            json_path = self._build_output_path(pub)
            if json_path.exists():
                pub.content_json_filepath = json_path
                self._cache_result(pub)

    def _run_worker_batch(self, publications: List[Publication]) -> None:
        """
        Converts the given PDFs in one MinerU worker process.

        Neither a per-PDF failure nor a non-zero worker exit (e.g. a native crash) is raised:
        MinerU may have converted part of the chunk, and transform2json() checks each output
        individually. Failures are logged.

        Parameters
        ----------
        publications : List[Publication] - Publications to convert.
            Callers are responsible for filtering out already-converted files.
        """
        if not publications:
            return

        with tempfile.TemporaryDirectory(prefix="mineru_job_") as tmp:
            job_path, results_path = Path(tmp) / "job.json", Path(tmp) / "results.json"
            job_path.write_text(json.dumps(self._build_job(publications, results_path)), encoding="utf-8")

            logging.info(f"MinerU batch starting: {len(publications)} PDF(s), tier={self.mineru_tier}.")
            result = subprocess.run(
                [sys.executable, "-m", "biomarkit.text_transformation.converters.mineru_worker", str(job_path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._build_worker_env(),
            )

            records = json.loads(results_path.read_text(encoding="utf-8")) if results_path.exists() else []

        for record in records:
            if not record["ok"]:
                logging.warning(f"MinerU failed on {record['pdf']}: {record['error']}")

        if result.returncode != 0:
            logging.warning(
                f"MinerU worker exited with code {result.returncode} after {len(records)}/{len(publications)} "
                f"PDF(s) — each publication's output is verified individually. "
                f"stderr (tail): {result.stderr.strip()[-2000:]}"
            )

    def _build_output_path(self, pub: Publication) -> Path:
        """
        Returns the path to the content_list_v2.json file for a publication:
        output_dir/<stem>/auto/<stem>_content_list_v2.json (see Transformer._build_output_path).

        Parameters
        ----------
        pub : Publication - Must have publication_filepath set.

        Returns
        -------
        Path - Path to the content_list_v2.json file produced by the worker.
        """
        stem = pub.publication_filepath.stem
        return self.output_dir / stem / "auto" / f"{stem}_content_list_v2.json"

    def transform2json(self, pub: Publication) -> Path | None:
        """
        Collects the content_list_v2.json produced for one publication by the batched
        MinerU run in transform_all().

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
