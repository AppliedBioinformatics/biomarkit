import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from biomarkit.text_download.basemodels.publication import Publication

MODULE = "biomarkit.text_transformation.converters.mineru_pdf_to_md"


def _make_pub(doi: str, tmp_path: Path) -> Publication:
    pub_file = tmp_path / f"{doi.replace('/', '_')}.pdf"
    pub_file.touch()
    return Publication(doi=doi, title="Test", publisher="TestPublisher",
                       year=2020, publication_filepath=pub_file)


def _make_md(converter, pub) -> Path:
    """Creates the content_list_v2.json file the worker would produce for pub and returns its path."""
    json_file = converter._build_output_path(pub)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.touch()
    return json_file


def _read_job(cmd) -> dict:
    """The worker job file is the last argument of the worker command."""
    return json.loads(Path(cmd[-1]).read_text(encoding="utf-8"))


def _job_pdf_names(cmd) -> list[str]:
    return sorted(Path(item["pdf"]).name for item in _read_job(cmd)["items"])


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

def test_init_sets_output_dir_to_raw_markdown_dir(active_corpus):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    converter = MinerUPdfTransformer(publication_list=[])
    assert converter.output_dir == active_corpus.json_dir


def test_init_defaults_to_standard_tier():
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    converter = MinerUPdfTransformer(publication_list=[])
    assert converter.mineru_tier == "standard"


@pytest.mark.parametrize("tier", ["basic", "standard", "advanced"])
def test_init_accepts_valid_tiers(tier):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    assert MinerUPdfTransformer(publication_list=[], mineru_tier=tier).mineru_tier == tier


@pytest.mark.parametrize("tier", ["flash", "local-gpu", "vllm", ""])
def test_init_rejects_unknown_tier(tier):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    with pytest.raises(ValueError, match="Invalid mineru_tier"):
        MinerUPdfTransformer(publication_list=[], mineru_tier=tier)


def test_init_rejects_non_positive_batch_size():
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    with pytest.raises(ValueError, match="batch_size"):
        MinerUPdfTransformer(publication_list=[], batch_size=0)


# ---------------------------------------------------------------------------
# _build_output_path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tier", ["basic", "standard", "advanced"])
def test_build_output_path_uses_auto_subdir_for_every_tier(tmp_path, tier):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    pub = _make_pub("10.1000/A", tmp_path)
    stem = pub.publication_filepath.stem
    converter = MinerUPdfTransformer(publication_list=[pub], mineru_tier=tier)
    converter.output_dir = tmp_path

    assert converter._build_output_path(pub) == tmp_path / stem / "auto" / f"{stem}_content_list_v2.json"


# ---------------------------------------------------------------------------
# transform2json — collects the output of the batched run
# ---------------------------------------------------------------------------

def test_convert_returns_json_path(tmp_path):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/D", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path
    md_file = _make_md(converter, pub)

    assert converter.transform2json(pub) == md_file


def test_convert_returns_none_when_json_missing(tmp_path):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/G", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    assert converter.transform2json(pub) is None


# ---------------------------------------------------------------------------
# transform_all — worker invocation
# ---------------------------------------------------------------------------

def test_transform_all_runs_one_worker_for_all_pubs(tmp_path):
    """All PDFs go to a single worker process, read in place, with output dirs matching _build_output_path."""
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pubs = [_make_pub(f"10.1000/{c}", tmp_path) for c in "ABC"]
    converter = MinerUPdfTransformer(publication_list=pubs, mineru_tier="basic")
    converter.output_dir = tmp_path / "intermediates"

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["job"] = _read_job(cmd)
        for pub in pubs:
            _make_md(converter, pub)
        return MagicMock(returncode=0, stderr="")

    with patch(f"{MODULE}.subprocess.run", side_effect=fake_run) as mock_run, \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    mock_run.assert_called_once()
    cmd, job = captured["cmd"], captured["job"]
    assert cmd[:3] == [sys.executable, "-m", "biomarkit.text_transformation.converters.mineru_worker"]
    assert job["tier"] == "basic"
    assert job["cleanup"] is True
    assert [item["pdf"] for item in job["items"]] == [str(p.publication_filepath) for p in pubs]
    assert [item["out_dir"] for item in job["items"]] == [str(converter._build_output_path(p).parent) for p in pubs]
    assert all(pub.content_json_filepath == converter._build_output_path(pub) for pub in pubs)


def test_transform_all_passes_cleanup_false(tmp_path):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/K", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub], cleanup=False)
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["job"] = _read_job(cmd)
        return MagicMock(returncode=0, stderr="")

    with patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    assert captured["job"]["cleanup"] is False


def test_transform_all_passes_remote_vlm_settings(tmp_path):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/R", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["job"] = _read_job(cmd)
        return MagicMock(returncode=0, stderr="")

    with patch(f"{MODULE}.MINERU_VLM_SERVER_URL", "http://vlm-host:30000"), \
         patch(f"{MODULE}.MINERU_VLM_API_KEY", "test-key"), \
         patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    assert captured["job"]["server_url"] == "http://vlm-host:30000"
    assert captured["job"]["api_key"] == "test-key"


def test_transform_all_local_vlm_sends_blank_server_settings(tmp_path):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/L", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["job"] = _read_job(cmd)
        return MagicMock(returncode=0, stderr="")

    with patch(f"{MODULE}.MINERU_VLM_SERVER_URL", None), \
         patch(f"{MODULE}.MINERU_VLM_API_KEY", None), \
         patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    assert captured["job"]["server_url"] == ""
    assert captured["job"]["api_key"] == ""


def test_transform_all_strips_legacy_mineru_env(tmp_path, monkeypatch):
    """MinerU 4 rejects a conflicting MINERU_VL_API_KEY, so legacy 3.x variables never reach the worker."""
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    monkeypatch.setenv("MINERU_VL_API_KEY", "old-key")
    monkeypatch.setenv("MINERU_VIRTUAL_VRAM_SIZE", "16")
    monkeypatch.setenv("SOME_OTHER_VAR", "kept")
    pub = _make_pub("10.1000/E", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return MagicMock(returncode=0, stderr="")

    with patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    assert "MINERU_VL_API_KEY" not in captured["env"]
    assert "MINERU_VIRTUAL_VRAM_SIZE" not in captured["env"]
    assert captured["env"]["SOME_OTHER_VAR"] == "kept"


def test_transform_all_logs_per_pdf_failures_from_results(tmp_path, caplog):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    ok_pub, bad_pub = _make_pub("10.1000/OK", tmp_path), _make_pub("10.1000/BAD", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[ok_pub, bad_pub])
    converter.output_dir = tmp_path

    def fake_run(cmd, **kwargs):
        _make_md(converter, ok_pub)
        Path(_read_job(cmd)["results"]).write_text(json.dumps([
            {"pdf": str(ok_pub.publication_filepath), "ok": True, "error": None},
            {"pdf": str(bad_pub.publication_filepath), "ok": False, "error": "ValueError: broken pdf"},
        ]), encoding="utf-8")
        return MagicMock(returncode=0, stderr="")

    with caplog.at_level("WARNING"), \
         patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result") as mock_cache:
        converter.transform_all()

    assert "ValueError: broken pdf" in caplog.text
    assert ok_pub.content_json_filepath == converter._build_output_path(ok_pub)
    assert bad_pub.content_json_filepath is None
    mock_cache.assert_called_once_with(ok_pub)


def test_transform_all_worker_crash_still_collects_outputs(tmp_path, caplog):
    """A crashed worker (non-zero exit, results partially or never written) is not fatal."""
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    ok_pub, bad_pub = _make_pub("10.1000/OK", tmp_path), _make_pub("10.1000/BAD", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[ok_pub, bad_pub])
    converter.output_dir = tmp_path

    def fake_run(cmd, **kwargs):
        _make_md(converter, ok_pub)
        return MagicMock(returncode=3221225477, stderr="Windows fatal exception: access violation")

    with caplog.at_level("WARNING"), \
         patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result") as mock_cache:
        converter.transform_all()

    assert "access violation" in caplog.text
    assert ok_pub.content_json_filepath == converter._build_output_path(ok_pub)
    assert bad_pub.content_json_filepath is None
    mock_cache.assert_called_once_with(ok_pub)


def test_transform_all_skips_worker_for_empty_list():
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    with patch(f"{MODULE}.subprocess.run") as mock_run:
        MinerUPdfTransformer(publication_list=[]).transform_all()

    mock_run.assert_not_called()


def test_transform_all_does_not_resend_existing_outputs(tmp_path):
    """Pubs whose JSON is already on disk are cached without being reconverted."""
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    done_pub = _make_pub("10.1000/DONE", tmp_path)
    new_pub = _make_pub("10.1000/NEW", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[done_pub, new_pub])
    converter.output_dir = tmp_path
    _make_md(converter, done_pub)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["pdfs"] = _job_pdf_names(cmd)
        _make_md(converter, new_pub)
        return MagicMock(returncode=0, stderr="")

    with patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result") as mock_cache:
        converter.transform_all()

    assert captured["pdfs"] == [new_pub.publication_filepath.name]
    assert done_pub.content_json_filepath == converter._build_output_path(done_pub)
    assert new_pub.content_json_filepath == converter._build_output_path(new_pub)
    assert mock_cache.call_count == 2


def test_transform_all_skips_worker_when_all_outputs_exist(tmp_path):
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pubs = [_make_pub(f"10.1000/{c}", tmp_path) for c in "AB"]
    converter = MinerUPdfTransformer(publication_list=pubs)
    converter.output_dir = tmp_path
    for pub in pubs:
        _make_md(converter, pub)

    with patch(f"{MODULE}.subprocess.run") as mock_run, \
         patch.object(converter, "_cache_result") as mock_cache:
        converter.transform_all()

    mock_run.assert_not_called()
    assert all(pub.content_json_filepath == converter._build_output_path(pub) for pub in pubs)
    assert mock_cache.call_count == 2


def test_transform_all_uses_base_class(tmp_path):
    """transform_all() uses the base class iteration (calls transform2json per pub)."""
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pubs = [_make_pub("10.1000/X", tmp_path)]
    converter = MinerUPdfTransformer(publication_list=pubs)

    with patch(f"{MODULE}.subprocess.run", return_value=MagicMock(returncode=0, stderr="")), \
         patch.object(converter, "transform2json", return_value=None) as mock_transform, \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    mock_transform.assert_called_once_with(pubs[0])


# ---------------------------------------------------------------------------
# Batching
# ---------------------------------------------------------------------------

def _run_batched(tmp_path, n_pubs, batch_size, pre_done=0):
    """Runs transform_all with a fake worker; returns (pubs, PDF names per worker call)."""
    from biomarkit.text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pubs = [_make_pub(f"10.1000/{i}", tmp_path) for i in range(n_pubs)]
    converter = MinerUPdfTransformer(publication_list=pubs, batch_size=batch_size)
    converter.output_dir = tmp_path
    for pub in pubs[:pre_done]:
        _make_md(converter, pub)

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(_job_pdf_names(cmd))
        for pub in pubs:
            _make_md(converter, pub)
        return MagicMock(returncode=0, stderr="")

    with patch(f"{MODULE}.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()
    return pubs, calls


def test_batching_splits_into_correct_number_of_calls(tmp_path):
    """7 pubs with batch_size=3 → 3 worker calls (chunks of 3, 3, 1)."""
    _, calls = _run_batched(tmp_path, 7, 3)
    assert [len(c) for c in calls] == [3, 3, 1]


def test_batching_covers_all_pubs(tmp_path):
    """Every publication is sent exactly once across the chunks."""
    pubs, calls = _run_batched(tmp_path, 5, 2)
    assert sorted(name for c in calls for name in c) == sorted(p.publication_filepath.name for p in pubs)


def test_batching_is_sequential_not_parallel(tmp_path):
    _, calls = _run_batched(tmp_path, 4, 2)
    assert len(calls) == 2
    assert calls[0] != calls[1]


@pytest.mark.parametrize("batch_size", [None, 3, 100])
def test_batch_size_at_or_above_pub_count_sends_one_call(tmp_path, batch_size):
    _, calls = _run_batched(tmp_path, 3, batch_size)
    assert len(calls) == 1


def test_already_converted_pubs_excluded_from_batching(tmp_path):
    pubs, calls = _run_batched(tmp_path, 5, 2, pre_done=1)
    sent = [name for c in calls for name in c]
    assert pubs[0].publication_filepath.name not in sent
    assert len(sent) == 4
