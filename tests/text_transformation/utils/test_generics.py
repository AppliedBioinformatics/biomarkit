import pytest
import os
from pathlib import Path
from unittest.mock import patch
import sys

def test_check_transformation_filepaths_creates_directories(active_corpus):
    from biomarkit.text_transformation.utils.generics import check_transformation_filepaths

    assert not active_corpus.json_dir.exists()
    assert not active_corpus.final_md_dir.exists()

    check_transformation_filepaths()

    assert active_corpus.json_dir.exists()
    assert active_corpus.final_md_dir.exists()


def test_check_transformation_filepaths_existing_directories(active_corpus):
    from biomarkit.text_transformation.utils.generics import check_transformation_filepaths

    # Pre-create dirs.
    for d in (active_corpus.json_dir, active_corpus.final_md_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Should not raise even if dirs already exist.
    check_transformation_filepaths()

    assert active_corpus.json_dir.exists()
    assert active_corpus.final_md_dir.exists()


# ---------------------------------------------------------------------------
# check_mineru
# ---------------------------------------------------------------------------

@patch("importlib.metadata.version", return_value="4.0.12")
def test_check_mineru_accepts_mineru_4(mock_version):
    from biomarkit.text_transformation.utils.generics import check_mineru
    assert check_mineru() == "4.0.12"
    mock_version.assert_called_once_with("mineru")


@pytest.mark.parametrize("installed", ["3.4.4", "2.7.0"])
def test_check_mineru_rejects_mineru_3_and_older(installed):
    from biomarkit.text_transformation.utils.generics import check_mineru
    with patch("importlib.metadata.version", return_value=installed):
        with pytest.raises(ImportError, match="requires MinerU 4"):
            check_mineru()


def test_check_mineru_raises_when_metadata_incomplete():
    """importlib.metadata.version() returns None for a half-uninstalled package."""
    from biomarkit.text_transformation.utils.generics import check_mineru
    with patch("importlib.metadata.version", return_value=None):
        with pytest.raises(ImportError, match="not installed"):
            check_mineru()


def test_check_mineru_raises_when_not_installed():
    from importlib.metadata import PackageNotFoundError
    from biomarkit.text_transformation.utils.generics import check_mineru
    with patch("importlib.metadata.version", side_effect=PackageNotFoundError("mineru")):
        with pytest.raises(ImportError, match="not installed"):
            check_mineru()


# ---------------------------------------------------------------------------
# check_gpu
# ---------------------------------------------------------------------------

def test_check_gpu_available():
    """check_gpu returns True when CUDA is available."""
    import torch
    from biomarkit.text_transformation.utils.generics import check_gpu

    with patch.object(torch.cuda, "is_available", return_value=True), \
         patch.object(torch.cuda, "device_count", return_value=1), \
         patch.object(torch.cuda, "get_device_name", return_value="Tesla T4"):
        result = check_gpu()

    assert result is True


def test_check_gpu_unavailable():
    """check_gpu returns False and warns when CUDA is not available."""
    import torch
    from biomarkit.text_transformation.utils.generics import check_gpu

    with patch.object(torch.cuda, "is_available", return_value=False), \
         patch.object(torch.cuda, "device_count", return_value=0):
        result = check_gpu()

    assert result is False


# ---------------------------------------------------------------------------
# prepare_bulk_transformation
# ---------------------------------------------------------------------------

GENERICS = "biomarkit.text_transformation.utils.generics"


@pytest.fixture
def preflight_mocks():
    """Patches the filesystem/cache/MinerU checks so prepare_bulk_transformation's own logic is tested."""
    with patch(f"{GENERICS}.check_transformation_filepaths") as filepaths, \
         patch(f"{GENERICS}.check_cache_for_markdowns") as cache, \
         patch(f"{GENERICS}.check_mineru") as mineru:
        yield type("Mocks", (), {"filepaths": filepaths, "cache": cache, "mineru": mineru})


@pytest.mark.parametrize("tier", ["basic", "standard", "advanced"])
def test_prepare_bulk_transformation_runs_all_checks(preflight_mocks, tier):
    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation
    with patch(f"{GENERICS}.check_gpu", return_value=True), patch("biomarkit.config.MINERU_VLM_SERVER_URL", None):
        prepare_bulk_transformation(mineru_tier=tier)
    preflight_mocks.filepaths.assert_called_once()
    preflight_mocks.cache.assert_called_once()
    preflight_mocks.mineru.assert_called_once()


@pytest.mark.parametrize("tier", ["flash", "local-gpu", "vllm"])
def test_prepare_bulk_transformation_rejects_unknown_tier(tier):
    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation
    with pytest.raises(ValueError, match="Invalid mineru_tier"):
        prepare_bulk_transformation(mineru_tier=tier)


def test_prepare_bulk_transformation_propagates_mineru_import_error(preflight_mocks):
    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation
    preflight_mocks.mineru.side_effect = ImportError("requires MinerU 4")
    with patch(f"{GENERICS}.check_gpu", return_value=True), patch("biomarkit.config.MINERU_VLM_SERVER_URL", None):
        with pytest.raises(ImportError, match="requires MinerU 4"):
            prepare_bulk_transformation()


@pytest.mark.parametrize("tier", ["standard", "advanced"])
def test_prepare_bulk_transformation_warns_vlm_tier_without_gpu_or_server(preflight_mocks, caplog, tier):
    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation
    with caplog.at_level("WARNING"), patch(f"{GENERICS}.check_gpu", return_value=False), \
         patch("biomarkit.config.MINERU_VLM_SERVER_URL", None):
        prepare_bulk_transformation(mineru_tier=tier)
    assert "very slow" in caplog.text


def test_prepare_bulk_transformation_basic_tier_does_not_check_gpu(preflight_mocks):
    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation
    with patch(f"{GENERICS}.check_gpu") as mock_gpu, patch("biomarkit.config.MINERU_VLM_SERVER_URL", None):
        prepare_bulk_transformation(mineru_tier="basic")
    mock_gpu.assert_not_called()


def test_prepare_bulk_transformation_remote_vlm_does_not_need_gpu(preflight_mocks, caplog):
    from biomarkit.text_transformation.utils.generics import prepare_bulk_transformation
    with caplog.at_level("WARNING"), patch(f"{GENERICS}.check_gpu") as mock_gpu, \
         patch("biomarkit.config.MINERU_VLM_SERVER_URL", "http://vlm-host:30000"):
        prepare_bulk_transformation(mineru_tier="standard")
    mock_gpu.assert_not_called()
    assert "very slow" not in caplog.text


# ---------------------------------------------------------------------------
# check_vlm_server_config
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url", [None, ""])
def test_check_vlm_server_config_unset_means_local(url):
    from biomarkit.text_transformation.utils.generics import check_vlm_server_config
    with patch("biomarkit.config.MINERU_VLM_SERVER_URL", url):
        assert check_vlm_server_config() is False


def test_check_vlm_server_config_set_means_remote():
    from biomarkit.text_transformation.utils.generics import check_vlm_server_config
    with patch("biomarkit.config.MINERU_VLM_SERVER_URL", "http://vlm-host:30000"):
        assert check_vlm_server_config() is True


def test_check_vlm_server_config_rejects_whitespace_url():
    from biomarkit.text_transformation.utils.generics import check_vlm_server_config
    with patch("biomarkit.config.MINERU_VLM_SERVER_URL", "   "):
        with pytest.raises(ValueError, match="MINERU_VLM_SERVER_URL"):
            check_vlm_server_config()


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

def _make_test_db(rows: list[dict]) -> None:
    """Helper — creates a fresh cache DB for the active corpus and inserts the given rows."""
    from biomarkit.config import get_corpus
    db = get_corpus().db
    db.parent.mkdir(parents=True, exist_ok=True)
    if db.exists():
        db.unlink()
    with _sqlite3.connect(db) as conn:
        conn.execute(DB_SCHEMA)
        conn.executemany(
            "INSERT INTO cache (doi, downloaded_from, publication_filepath, content_json_filepath, final_md_filepath) "
            "VALUES (:doi, :downloaded_from, :publication_filepath, :content_json_filepath, :final_md_filepath)",
            rows,
        )


def test_check_cache_for_markdowns_empty_db(caplog):
    """Logs correct counts when the cache is empty."""
    from biomarkit.text_transformation.utils.generics import check_cache_for_markdowns

    _make_test_db([])

    with caplog.at_level("INFO", logger="root"):
        check_cache_for_markdowns()

    assert "0 publication(s) in cache" in caplog.text
    assert "0 with raw markdown" in caplog.text
    assert "0 with final markdown" in caplog.text

@pytest.mark.skipif(os.name == 'nt', reason="Permission issues on Windows")
def test_check_cache_for_markdowns_mixed(caplog):
    """Logs correct counts for a mix of processed and unprocessed publications."""
    from biomarkit.text_transformation.utils.generics import check_cache_for_markdowns

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
def test_check_cache_for_markdowns_returns_none():
    """Function returns None (log-only, no return value)."""
    from biomarkit.text_transformation.utils.generics import check_cache_for_markdowns

    _make_test_db([])
    result = check_cache_for_markdowns()
    assert result is None


# ---------------------------------------------------------------------------
# cleanup_intermediate_files
# ---------------------------------------------------------------------------

def _make_fake_auto_dir(tmp_path: Path) -> tuple:
    """Returns (auto_dir, json_path) with realistic MinerU output structure."""
    auto_dir = tmp_path / "stem" / "auto"
    auto_dir.mkdir(parents=True)
    json_path = auto_dir / "stem_content_list_v2.json"
    json_path.write_text('{"pages": []}')
    (auto_dir / "stem.md").write_text("raw markdown")
    (auto_dir / "stem_model.json").write_text("{}")
    images_dir = auto_dir / "images"
    images_dir.mkdir()
    (images_dir / "fig1.jpg").write_bytes(b"\xff")
    return auto_dir, json_path


class _FakePub:
    def __init__(self, content_json_filepath):
        self.content_json_filepath = content_json_filepath


def test_cleanup_deletes_non_json_files_but_keeps_images(tmp_path):
    from biomarkit.text_transformation.utils.generics import cleanup_intermediate_files

    auto_dir, json_path = _make_fake_auto_dir(tmp_path)
    pub = _FakePub(json_path)

    cleanup_intermediate_files([pub])

    assert sorted(p.name for p in auto_dir.iterdir()) == sorted([json_path.name, "images"])
    assert (auto_dir / "images" / "fig1.jpg").exists()


def test_prune_intermediate_dir_removes_mineru4_outputs(tmp_path):
    from biomarkit.text_transformation.utils.generics import prune_intermediate_dir

    auto_dir, json_path = _make_fake_auto_dir(tmp_path)
    for name in ("middle_json.json", "markdown.md", "structured_content.json", "model_output.json"):
        (auto_dir / name).write_text("{}")
    (auto_dir / "other_dir").mkdir()

    deleted = prune_intermediate_dir(json_path)

    assert sorted(p.name for p in auto_dir.iterdir()) == sorted([json_path.name, "images"])
    assert deleted == 7  # 4 MinerU 4 files + stem.md + stem_model.json + other_dir


def test_cleanup_keeps_json_intact(tmp_path):
    from biomarkit.text_transformation.utils.generics import cleanup_intermediate_files

    auto_dir, json_path = _make_fake_auto_dir(tmp_path)
    pub = _FakePub(json_path)

    cleanup_intermediate_files([pub])

    assert json_path.exists()
    assert json_path.read_text() == '{"pages": []}'


def test_cleanup_skips_pub_without_content_json_filepath():
    from biomarkit.text_transformation.utils.generics import cleanup_intermediate_files

    pub = _FakePub(None)
    cleanup_intermediate_files([pub])  # should not raise
