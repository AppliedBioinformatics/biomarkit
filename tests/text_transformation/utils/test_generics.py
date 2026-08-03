import pytest
import os
from pathlib import Path
from unittest.mock import patch
from config import TMP_DIR
import sys

RAW_MD = TMP_DIR / "test_raw_markdown"
FINAL_MD = TMP_DIR / "test_final_markdown"


@patch("text_transformation.utils.generics.JSON_STRUCT_DIR", RAW_MD)
@patch("text_transformation.utils.generics.FINAL_MARKDOWN_DIR", FINAL_MD)
def test_check_transformation_filepaths_creates_directories():
    from text_transformation.utils.generics import check_transformation_filepaths

    # Ensure dirs don't exist before the call.
    for d in (RAW_MD, FINAL_MD):
        if d.exists():
            d.rmdir()

    check_transformation_filepaths()

    assert RAW_MD.exists()
    assert FINAL_MD.exists()

    # Cleanup.
    for d in (RAW_MD, FINAL_MD):
        d.rmdir()


@patch("text_transformation.utils.generics.JSON_STRUCT_DIR", RAW_MD)
@patch("text_transformation.utils.generics.FINAL_MARKDOWN_DIR", FINAL_MD)
def test_check_transformation_filepaths_existing_directories():
    from text_transformation.utils.generics import check_transformation_filepaths

    # Pre-create dirs.
    for d in (RAW_MD, FINAL_MD):
        d.mkdir(parents=True, exist_ok=True)

    # Should not raise even if dirs already exist.
    check_transformation_filepaths()

    assert RAW_MD.exists()
    assert FINAL_MD.exists()

    # Cleanup.
    for d in (RAW_MD, FINAL_MD):
        d.rmdir()


FAKE_VENV_DIR = TMP_DIR / "tests_tmp"
FAKE_VENV_MINERU = FAKE_VENV_DIR / ".venv" / "Scripts" / "mineru.exe"


@patch("text_transformation.utils.generics.BASE_DIR", FAKE_VENV_DIR)
def test_find_mineru_finds_venv_executable():
    from text_transformation.utils.generics import check_mineru

    FAKE_VENV_MINERU.parent.mkdir(parents=True, exist_ok=True)
    FAKE_VENV_MINERU.touch()

    result = check_mineru()

    assert result == FAKE_VENV_MINERU

    FAKE_VENV_MINERU.unlink()


@patch("text_transformation.utils.generics.BASE_DIR", FAKE_VENV_DIR)
@patch("text_transformation.utils.generics.shutil.which", return_value="C:/tools/mineru.exe")
def test_find_mineru_falls_back_to_global(mock_which):
    from text_transformation.utils.generics import check_mineru

    if FAKE_VENV_MINERU.exists():
        FAKE_VENV_MINERU.unlink()

    result = check_mineru()

    assert result == Path("C:/tools/mineru.exe")
    mock_which.assert_called_once_with("mineru")


@patch("text_transformation.utils.generics.BASE_DIR", FAKE_VENV_DIR)
@patch("text_transformation.utils.generics.shutil.which", return_value=None)
def test_find_mineru_raises_when_not_found(mock_which):
    from text_transformation.utils.generics import check_mineru

    if FAKE_VENV_MINERU.exists():
        FAKE_VENV_MINERU.unlink()

    with pytest.raises(FileNotFoundError, match="MinerU executable not found"):
        check_mineru()


# ---------------------------------------------------------------------------
# check_gpu
# ---------------------------------------------------------------------------

def test_check_gpu_available():
    """check_gpu returns True when CUDA is available."""
    import torch
    from text_transformation.utils.generics import check_gpu

    with patch.object(torch.cuda, "is_available", return_value=True), \
         patch.object(torch.cuda, "device_count", return_value=1), \
         patch.object(torch.cuda, "get_device_name", return_value="Tesla T4"):
        result = check_gpu()

    assert result is True


def test_check_gpu_unavailable():
    """check_gpu returns False and warns when CUDA is not available."""
    import torch
    from text_transformation.utils.generics import check_gpu

    with patch.object(torch.cuda, "is_available", return_value=False), \
         patch.object(torch.cuda, "device_count", return_value=0):
        result = check_gpu()

    assert result is False


# ---------------------------------------------------------------------------
# prepare_bulk_transformation
# ---------------------------------------------------------------------------

@patch("text_transformation.utils.generics.check_cache_for_markdowns")
@patch("text_transformation.utils.generics.check_mineru")
@patch("text_transformation.utils.generics.check_gpu", return_value=True)
@patch("text_transformation.utils.generics.check_transformation_filepaths")
def test_prepare_bulk_transformation_success(mock_filepaths, mock_gpu, mock_mineru, mock_cache):
    from text_transformation.utils.generics import prepare_bulk_transformation

    prepare_bulk_transformation()

    mock_filepaths.assert_called_once()
    mock_gpu.assert_called_once()
    mock_mineru.assert_called_once()


@patch("text_transformation.utils.generics.check_cache_for_markdowns")
@patch("text_transformation.utils.generics.check_mineru")
@patch("text_transformation.utils.generics.check_gpu", return_value=False)
@patch("text_transformation.utils.generics.check_transformation_filepaths")
def test_prepare_bulk_transformation_raises_when_no_gpu(mock_filepaths, mock_gpu, mock_mineru, mock_cache):
    from text_transformation.utils.generics import prepare_bulk_transformation

    with pytest.raises(RuntimeError, match="No GPU recognised"):
        prepare_bulk_transformation()

    mock_mineru.assert_not_called()


@patch("text_transformation.utils.generics.check_cache_for_markdowns")
@patch("text_transformation.utils.generics.check_mineru", side_effect=FileNotFoundError("MinerU executable not found"))
@patch("text_transformation.utils.generics.check_gpu", return_value=True)
@patch("text_transformation.utils.generics.check_transformation_filepaths")
def test_prepare_bulk_transformation_raises_when_mineru_missing(mock_filepaths, mock_gpu, mock_mineru, mock_cache):
    from text_transformation.utils.generics import prepare_bulk_transformation

    with pytest.raises(FileNotFoundError, match="MinerU executable not found"):
        prepare_bulk_transformation()


def test_prepare_bulk_transformation_rejects_unknown_endpoint():
    from text_transformation.utils.generics import prepare_bulk_transformation

    with pytest.raises(ValueError, match="Invalid mineru_backend"):
        prepare_bulk_transformation(mineru_backend="remote")


@patch("text_transformation.utils.generics.check_cache_for_markdowns")
@patch("text_transformation.utils.generics.check_mineru")
@patch("text_transformation.utils.generics.check_gpu", return_value=False)
@patch("text_transformation.utils.generics.check_transformation_filepaths")
@patch("text_transformation.utils.generics.check_vllm_config")
def test_prepare_bulk_transformation_vllm_tolerates_missing_gpu(
    mock_vllm, mock_filepaths, mock_gpu, mock_mineru, mock_cache
):
    """With remote inference the missing local GPU is a warning, not an error."""
    from text_transformation.utils.generics import prepare_bulk_transformation

    prepare_bulk_transformation(mineru_backend="vllm")

    mock_vllm.assert_called_once()
    mock_mineru.assert_called_once()


@patch("text_transformation.utils.generics.check_cache_for_markdowns")
@patch("text_transformation.utils.generics.check_mineru")
@patch("text_transformation.utils.generics.check_gpu", return_value=True)
@patch("text_transformation.utils.generics.check_transformation_filepaths")
def test_prepare_bulk_transformation_vllm_raises_when_secrets_missing(
    mock_filepaths, mock_gpu, mock_mineru, mock_cache
):
    from text_transformation.utils.generics import prepare_bulk_transformation

    with patch("config.MINERU_VLLM_ENDPOINT", None), patch("config.MINERU_API_KEY", None):
        with pytest.raises(ValueError, match="MINERU_VLLM_ENDPOINT and MINERU_API_KEY"):
            prepare_bulk_transformation(mineru_backend="vllm")

    mock_mineru.assert_not_called()


# ---------------------------------------------------------------------------
# check_vllm_config
# ---------------------------------------------------------------------------

def test_check_vllm_config_passes_when_both_set():
    from text_transformation.utils.generics import check_vllm_config

    with patch("config.MINERU_VLLM_ENDPOINT", "http://vllm-host:30000"), \
         patch("config.MINERU_API_KEY", "test-key"):
        check_vllm_config()


@pytest.mark.parametrize("endpoint, key, expected", [
    (None, None, "MINERU_VLLM_ENDPOINT and MINERU_API_KEY"),
    ("", "", "MINERU_VLLM_ENDPOINT and MINERU_API_KEY"),
    ("http://vllm-host:30000", None, "MINERU_API_KEY"),
    (None, "test-key", "MINERU_VLLM_ENDPOINT"),
    ("   ", "test-key", "MINERU_VLLM_ENDPOINT"),
])
def test_check_vllm_config_raises_when_unfilled(endpoint, key, expected):
    from text_transformation.utils.generics import check_vllm_config

    with patch("config.MINERU_VLLM_ENDPOINT", endpoint), patch("config.MINERU_API_KEY", key):
        with pytest.raises(ValueError, match=expected):
            check_vllm_config()


# ---------------------------------------------------------------------------
# check_cache_for_markdowns
# ---------------------------------------------------------------------------

import sqlite3 as _sqlite3

DB_SCHEMA = """
    CREATE TABLE IF NOT EXISTS cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT UNIQUE NOT NULL,
    downloaded_from TEXT NOT NULL,
    publication_filepath TEXT NOT NULL,
    content_json_filepath TEXT,
    final_md_filepath TEXT)
"""

TMP_TEST_DB = TMP_DIR / "tests_tmp" / "test_cache_markdowns.sqlite"

@pytest.mark.skipif(sys.platform == "win32", reason="Does not run on Windows")
def _make_test_db(rows: list[dict]) -> None:
    """Helper — creates a fresh test DB and inserts the given rows."""
    TMP_TEST_DB.parent.mkdir(parents=True, exist_ok=True)
    if TMP_TEST_DB.exists():
        TMP_TEST_DB.unlink()
    with _sqlite3.connect(TMP_TEST_DB) as conn:
        conn.execute(DB_SCHEMA)
        conn.executemany(
            "INSERT INTO cache (doi, downloaded_from, publication_filepath, content_json_filepath, final_md_filepath) "
            "VALUES (:doi, :downloaded_from, :publication_filepath, :content_json_filepath, :final_md_filepath)",
            rows,
        )


@patch("text_transformation.utils.generics.DB_CACHE_FILE_NAME", TMP_TEST_DB)
def test_check_cache_for_markdowns_empty_db(caplog):
    """Logs correct counts when the cache is empty."""
    from text_transformation.utils.generics import check_cache_for_markdowns

    _make_test_db([])

    with caplog.at_level("INFO", logger="root"):
        check_cache_for_markdowns()

    assert "0 publication(s) in cache" in caplog.text
    assert "0 with raw markdown" in caplog.text
    assert "0 with final markdown" in caplog.text

@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
@patch("text_transformation.utils.generics.DB_CACHE_FILE_NAME", TMP_TEST_DB)
def test_check_cache_for_markdowns_mixed(caplog):
    """Logs correct counts for a mix of processed and unprocessed publications."""
    from text_transformation.utils.generics import check_cache_for_markdowns

    _make_test_db([
        {"doi": "10.1/a", "downloaded_from": "unpaywall", "publication_filepath": "/f/a.pdf",
         "content_json_filepath": "/r/a.md", "final_md_filepath": "/f/a.md"},
        {"doi": "10.1/b", "downloaded_from": "wiley",     "publication_filepath": "/f/b.pdf",
         "content_json_filepath": "/r/b.md", "final_md_filepath": None},
        {"doi": "10.1/c", "downloaded_from": "springer",  "publication_filepath": "/f/c.pdf",
         "content_json_filepath": None,      "final_md_filepath": None},
    ])

    with caplog.at_level("INFO", logger="root"):
        check_cache_for_markdowns()

    assert "3 publication(s) in cache" in caplog.text
    assert "2 with raw markdown" in caplog.text
    assert "1 with final markdown" in caplog.text


@pytest.mark.skipif(sys.platform == "win32", reason="Does not run on Windows")
@patch("text_transformation.utils.generics.DB_CACHE_FILE_NAME", TMP_TEST_DB)
def test_check_cache_for_markdowns_returns_none():
    """Function returns None (log-only, no return value)."""
    from text_transformation.utils.generics import check_cache_for_markdowns

    _make_test_db([])
    result = check_cache_for_markdowns()
    assert result is None
