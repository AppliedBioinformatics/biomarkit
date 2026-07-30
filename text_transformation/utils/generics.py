import logging
import shutil
import sqlite3
from pathlib import Path
from config import RAW_MARKDOWN_DIR, FINAL_MARKDOWN_DIR, BASE_DIR, DB_CACHE_FILE

MINERU_ENDPOINT_CHOICES = ("local", "vllm")

def prepare_bulk_transformation(mineru_endpoint: str = "local") -> None:
    """
    Carries out pre-flight checks before launching the text-transformation pipeline.

    Parameters
    ----------
    mineru_endpoint : str - "local" runs MinerU inference on the local GPU (default);
        "vllm" sends inference to the remote vLLM server configured in secrets.env,
        in which case no local GPU is required.

    Raises
    ------
    ValueError - If mineru_endpoint is not a recognised choice, or if
        mineru_endpoint="vllm" and MINERU_VLLM_ENDPOINT / MINERU_API_KEY are unset.
    FileNotFoundError - If the mineru executable cannot be located.
    RuntimeError - If mineru_endpoint="local" and no CUDA-capable GPU is recognized by PyTorch.
    """
    if mineru_endpoint not in MINERU_ENDPOINT_CHOICES:
        raise ValueError(
            f"Invalid mineru_endpoint: {mineru_endpoint!r}. "
            f"Allowed values: {', '.join(MINERU_ENDPOINT_CHOICES)}."
        )

    check_transformation_filepaths()
    check_cache_for_markdowns()

    if mineru_endpoint == "vllm":
        check_vllm_config()
        if not check_gpu():
            logging.warning(
                "No local GPU recognised — proceeding anyway as MinerU inference "
                "is delegated to the remote vLLM endpoint."
            )
    elif not check_gpu():
        raise RuntimeError("No GPU recognised by PyTorch. Cannot proceed.")
    check_mineru()


def check_vllm_config() -> None:
    """
    Affirms that the remote MinerU vLLM settings are filled in secrets.env.
    Required before running transform_text(mineru_endpoint="vllm").

    Raises
    ------
    ValueError - If MINERU_VLLM_ENDPOINT or MINERU_API_KEY is unset or blank.
    """
    from config import MINERU_VLLM_ENDPOINT, MINERU_API_KEY

    missing = [
        name for name, value in (
            ("MINERU_VLLM_ENDPOINT", MINERU_VLLM_ENDPOINT),
            ("MINERU_API_KEY", MINERU_API_KEY),
        )
        if not (value and value.strip())
    ]
    if missing:
        raise ValueError(
            f"mineru_endpoint='vllm' requires {' and '.join(missing)} to be set in secrets.env."
        )
    logging.info(f"MinerU remote inference configured: {MINERU_VLLM_ENDPOINT}")

def check_transformation_filepaths() -> None:
    """
    Checks that RAW_MARKDOWN_DIR and FINAL_MARKDOWN_DIR exist, creating them if not.
    """
    for directory in (RAW_MARKDOWN_DIR, FINAL_MARKDOWN_DIR):
        if not directory.exists():
            logging.info(f"SETUP - Directory not found, creating: {directory}")
            directory.mkdir(parents=True, exist_ok=True)
        else:
            logging.info(f"SETUP - Directory exists: {directory}")


def check_mineru() -> Path:
    """
    Locates the MinerU CLI executable, checking the local .venv first
    then falling back to the global PATH.

    Returns
    -------
    Path - Path to the mineru executable.

    Raises
    ------
    FileNotFoundError - If the mineru executable is not found in the .venv or on the global PATH.
    """
    venv_mineru = BASE_DIR / ".venv" / "Scripts" / "mineru.exe"
    if venv_mineru.exists():
        logging.info(f"MinerU found in .venv: {venv_mineru}")
        return venv_mineru

    global_mineru = shutil.which("mineru")
    if global_mineru:
        logging.info(f"MinerU found on global PATH: {global_mineru}")
        return Path(global_mineru)

    raise FileNotFoundError("MinerU executable not found in .venv or global PATH.")


def check_gpu() -> bool:
    """
    Checks whether a CUDA-capable GPU is recognized by PyTorch.

    Returns
    -------
    bool - True if at least one GPU is available, False otherwise.
    """
    import torch
    available = torch.cuda.is_available()
    device_count = torch.cuda.device_count()

    if available:
        device_name = torch.cuda.get_device_name(0)
        logging.info(f"GPU available: {device_count} device(s) found. Primary: {device_name}")
    else:
        logging.warning("No GPU recognised by PyTorch.")
    return available

def check_cache_for_markdowns() -> None:
    """
    Checks the cache to see if any publications have already been processed. Controller will handle splitting of
    files this function just checks whether any are present and updates the log."""
    with sqlite3.connect(DB_CACHE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cache WHERE raw_md_filepath IS NOT NULL")
        raw_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cache WHERE final_md_filepath IS NOT NULL")
        final_count = cursor.fetchone()[0]

    logging.info(f"CACHE - {total} publication(s) in cache. "
                 f"{raw_count} with raw markdown, {final_count} with final markdown.")

def finalise_transformation(publications: list) -> list:
    """
    Validates and returns publications after text transformation for handoff to the standardiser.

    Logs how many publications have ``raw_md_filepath`` set and asserts the ready subset is
    internally consistent (no pub in that subset is missing its filepath).

    Parameters
    ----------
    publications : list[Publication]
        Combined list of all publications from the transformation controller
        (needs_conversion + needs_processing + fully_processed).

    Returns
    -------
    list[Publication]
        The same list, unmodified.  Returning the full list (not just those with
        raw_md_filepath) gives the standardiser visibility over failures too.
    """
    ready = [pub for pub in publications if pub.raw_md_filepath is not None]
    logging.info(
        f"transform_text complete — {len(ready)}/{len(publications)} "
        "publication(s) have raw_md_filepath set."
    )
    assert all(pub.raw_md_filepath is not None for pub in ready), \
        "Invariant violation: ready pub missing raw_md_filepath"
    return publications


if __name__ == "__main__":
    check_mineru()