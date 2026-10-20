import logging
import shutil
import sqlite3
from pathlib import Path
from biomarkit.config import MINERU_TIER_CHOICES, get_corpus

# Oldest MinerU major version whose Python SDK the converter supports.
MINERU_MIN_MAJOR_VERSION = 4


def prepare_bulk_transformation(mineru_tier: str = "standard") -> None:
    """
    Carries out pre-flight checks before launching the text-transformation pipeline.

    Parameters
    ----------
    mineru_tier : str - MinerU parsing tier: "basic" (small models only, CPU-friendly),
        "standard" (default; small models + VLM) or "advanced" (more VLM compute for hard documents).

    Raises
    ------
    ValueError - If mineru_tier is not a recognised choice, or MINERU_VLM_SERVER_URL is blank.
    ImportError - If MinerU 4 or newer is not installed.
    """
    if mineru_tier not in MINERU_TIER_CHOICES:
        raise ValueError(
            f"Invalid mineru_tier: {mineru_tier!r}. "
            f"Allowed values: {', '.join(MINERU_TIER_CHOICES)}."
        )

    check_transformation_filepaths()
    check_cache_for_markdowns()

    remote_vlm = check_vlm_server_config()
    if mineru_tier != "basic" and not remote_vlm and not check_gpu():
        logging.warning(
            f"No GPU recognised and no MINERU_VLM_SERVER_URL set — mineru_tier={mineru_tier!r} will run the "
            f"MinerU VLM on CPU, which is very slow. Consider mineru_tier='basic' or a remote VLM server."
        )
    check_mineru()


def check_vlm_server_config() -> bool:
    """
    Checks the optional remote MinerU VLM settings in secrets.env.

    Returns
    -------
    bool - True if a remote VLM server is configured, False if the VLM runs locally.

    Raises
    ------
    ValueError - If MINERU_VLM_SERVER_URL is present but blank or whitespace.
    """
    from biomarkit.config import MINERU_VLM_SERVER_URL

    if MINERU_VLM_SERVER_URL is None or MINERU_VLM_SERVER_URL == "":
        return False
    if not MINERU_VLM_SERVER_URL.strip():
        raise ValueError("MINERU_VLM_SERVER_URL in secrets.env is blank — set a server URL or remove it.")
    logging.info(f"MinerU remote VLM configured: {MINERU_VLM_SERVER_URL}")
    return True

def check_transformation_filepaths() -> None:
    """
    Checks that the active corpus's intermediates and results folders exist, creating them if not.
    """
    for directory in (get_corpus().json_dir, get_corpus().final_md_dir):
        if not directory.exists():
            logging.info(f"SETUP - Directory not found, creating: {directory}")
            directory.mkdir(parents=True, exist_ok=True)
        else:
            logging.info(f"SETUP - Directory exists: {directory}")


def check_mineru() -> str:
    """
    Checks that a supported MinerU version (4 or newer) is installed in this environment.

    Returns
    -------
    str - The installed MinerU version.

    Raises
    ------
    ImportError - If MinerU is not installed, or is older than MINERU_MIN_MAJOR_VERSION.
    """
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("mineru")
    except PackageNotFoundError:
        installed = None
    # version() returns None (rather than raising) when the package's metadata is incomplete.
    if not installed:
        raise ImportError("MinerU is not installed. Install it with: pip install \"mineru[torch]>=4.0.12,<5\"")

    if int(installed.split(".")[0]) < MINERU_MIN_MAJOR_VERSION:
        raise ImportError(
            f"MinerU {installed} is installed, but biomarkit requires MinerU {MINERU_MIN_MAJOR_VERSION} or newer. "
            f"Upgrade with: pip install -U \"mineru[torch]>=4.0.12,<5\""
        )
    logging.info(f"MinerU {installed} found.")
    return installed

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
    with sqlite3.connect(get_corpus().db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM cache")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cache WHERE content_json_filepath IS NOT NULL")
        raw_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM cache WHERE final_md_filepath IS NOT NULL")
        final_count = cursor.fetchone()[0]

    logging.info(f"CACHE - {total} publication(s) in cache. "
                 f"{raw_count} with raw markdown, {final_count} with final markdown.")

def finalise_transformation(publications: list) -> list:
    """
    Validates and returns publications after text transformation for handoff to the standardiser.

    Logs how many publications have ``content_json_filepath`` set and asserts the ready subset is
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
        content_json_filepath) gives the standardiser visibility over failures too.
    """
    ready = [pub for pub in publications if pub.content_json_filepath is not None]
    logging.debug(
        f"transform_text complete — {len(ready)}/{len(publications)} "
        "publication(s) have content_json_filepath set."
    )
    assert all(pub.content_json_filepath is not None for pub in ready), \
        "Invariant violation: ready pub missing content_json_filepath"
    return publications


def prune_intermediate_dir(content_json_path: Path) -> int:
    """
    Deletes everything in a publication's intermediates folder except its content_list_v2.json and the
    images/ folder it links to (needed for figure links when standardise_text(keep_figures=True)).

    Parameters
    ----------
    content_json_path : Path - The publication's content_list_v2.json.

    Returns
    -------
    int - Number of files/folders deleted.
    """
    deleted = 0
    for item in content_json_path.parent.iterdir():
        if item == content_json_path or (item.is_dir() and item.name == "images"):
            continue
        if item.is_dir():
            shutil.rmtree(item)
        else:
            item.unlink()
        deleted += 1
    return deleted


def cleanup_intermediate_files(publications: list) -> None:
    """
    Delete non-essential files produced by MinerU from each publication's intermediates
    directory, keeping only the *_content_list_v2.json and its images/ folder.
    Publications without content_json_filepath are silently skipped.
    """
    deleted = sum(
        prune_intermediate_dir(Path(pub.content_json_filepath))
        for pub in publications if pub.content_json_filepath is not None
    )
    logging.debug(f"cleanup_intermediate_files: removed {deleted} items from intermediates/.")


if __name__ == "__main__":
    print(check_mineru())