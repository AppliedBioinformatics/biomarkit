from pathlib import Path
from unittest.mock import patch, MagicMock
from text_download.basemodels.publication import Publication


def _make_pub(doi: str, tmp_path: Path) -> Publication:
    pub_file = tmp_path / f"{doi.replace('/', '_')}.pdf"
    pub_file.touch()
    return Publication(doi=doi, title="Test", publisher="TestPublisher",
                       year=2020, publication_filepath=pub_file)


def _make_md(converter, pub) -> Path:
    """Creates the content_list_v2.json file MinerU would produce for pub and returns its path."""
    json_file = converter._build_output_path(pub)
    json_file.parent.mkdir(parents=True, exist_ok=True)
    json_file.touch()
    return json_file


FAKE_MINERU = Path("/fake/mineru.exe")


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------

def test_init_sets_output_dir_to_raw_markdown_dir():
    from config import JSON_STRUCT_DIR
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    converter = MinerUPdfTransformer(publication_list=[])
    assert converter.output_dir == JSON_STRUCT_DIR


def test_init_defaults_to_local_gpu():
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    converter = MinerUPdfTransformer(publication_list=[])
    assert converter.mineru_backend == "local-gpu"


def test_init_rejects_unknown_endpoint():
    import pytest
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    with pytest.raises(ValueError, match="Invalid mineru_backend"):
        MinerUPdfTransformer(publication_list=[], mineru_backend="remote")


# ---------------------------------------------------------------------------
# _build_output_path
# ---------------------------------------------------------------------------

def test_build_output_path_uses_mineru_structure(tmp_path):
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    pub = _make_pub("10.1000/A", tmp_path)
    stem = pub.publication_filepath.stem
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    result = converter._build_output_path(pub)

    assert result == tmp_path / stem / "auto" / f"{stem}_content_list_v2.json"


def test_build_output_path_uses_vlm_subdir_for_vllm_endpoint(tmp_path):
    """The vlm-http-client backend nests output under vlm/, not auto/."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer
    pub = _make_pub("10.1000/A", tmp_path)
    stem = pub.publication_filepath.stem
    converter = MinerUPdfTransformer(publication_list=[pub], mineru_backend="vllm")
    converter.output_dir = tmp_path

    result = converter._build_output_path(pub)

    assert result == tmp_path / stem / "vlm" / f"{stem}_content_list_v2.json"


# ---------------------------------------------------------------------------
# convert — collects the output of the batched run
# ---------------------------------------------------------------------------

def test_convert_returns_json_path(tmp_path):
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/D", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path
    md_file = _make_md(converter, pub)

    result = converter.transform2json(pub)

    assert result == md_file


def test_convert_returns_none_when_json_missing(tmp_path):
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/G", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    result = converter.transform2json(pub)

    assert result is None


# ---------------------------------------------------------------------------
# convert_all — single batched MinerU invocation
# ---------------------------------------------------------------------------

def test_convert_all_runs_mineru_once_for_all_pubs(tmp_path):
    """All PDFs are staged into one directory and converted in a single call."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer, MINERU_OCR_LANG

    pubs = [_make_pub(f"10.1000/{c}", tmp_path) for c in "ABC"]
    converter = MinerUPdfTransformer(publication_list=pubs)
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        staging_dir = Path(cmd[cmd.index("-p") + 1])
        captured["staged"] = sorted(p.name for p in staging_dir.iterdir())
        for pub in pubs:
            _make_md(converter, pub)
        return MagicMock(returncode=0)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", side_effect=fake_run) as mock_run, \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    mock_run.assert_called_once()
    assert captured["staged"] == sorted(pub.publication_filepath.name for pub in pubs)
    cmd = captured["cmd"]
    assert cmd[0] == str(FAKE_MINERU)
    assert cmd[cmd.index("-o") + 1] == str(tmp_path)
    assert cmd[cmd.index("-b") + 1] == "pipeline"
    assert cmd[cmd.index("-l") + 1] == MINERU_OCR_LANG
    assert all(pub.content_json_filepath == converter._build_output_path(pub) for pub in pubs)


def test_convert_all_vllm_uses_http_client_backend(tmp_path):
    """vllm mode passes -b vlm-http-client, points -u at the configured endpoint,
    exposes the API key as MINERU_VL_API_KEY, and omits the pipeline-only -l flag."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/R", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub], mineru_backend="vllm")
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        _make_md(converter, pub)
        return MagicMock(returncode=0)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.MINERU_VLLM_ENDPOINT", "http://vllm-host:30000"), \
         patch("text_transformation.converters.mineru_pdf_to_md.MINERU_API_KEY", "test-key"), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    cmd = captured["cmd"]
    assert cmd[cmd.index("-b") + 1] == "vlm-http-client"
    assert cmd[cmd.index("-u") + 1] == "http://vllm-host:30000"
    assert "-l" not in cmd
    assert captured["env"]["MINERU_VL_API_KEY"] == "test-key"
    assert pub.content_json_filepath == converter._build_output_path(pub)


def test_convert_all_local_does_not_leak_vl_api_key(tmp_path, monkeypatch):
    """Local mode must not set MINERU_VL_API_KEY even when the secret is configured."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    monkeypatch.delenv("MINERU_VL_API_KEY", raising=False)
    pub = _make_pub("10.1000/L", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return MagicMock(returncode=0)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.MINERU_API_KEY", "test-key"), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    assert "MINERU_VL_API_KEY" not in captured["env"]


def test_convert_all_skips_batch_for_empty_list():
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    converter = MinerUPdfTransformer(publication_list=[])

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run") as mock_run:
        converter.transform_all()

    mock_run.assert_not_called()


def test_convert_all_does_not_restage_existing_outputs(tmp_path):
    """Pubs whose .md is already on disk are cached without being reconverted."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    done_pub = _make_pub("10.1000/DONE", tmp_path)
    new_pub = _make_pub("10.1000/NEW", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[done_pub, new_pub])
    converter.output_dir = tmp_path
    _make_md(converter, done_pub)

    captured = {}

    def fake_run(cmd, **kwargs):
        staging_dir = Path(cmd[cmd.index("-p") + 1])
        captured["staged"] = sorted(p.name for p in staging_dir.iterdir())
        _make_md(converter, new_pub)
        return MagicMock(returncode=0)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result") as mock_cache:
        converter.transform_all()

    assert captured["staged"] == [new_pub.publication_filepath.name]
    assert done_pub.content_json_filepath == converter._build_output_path(done_pub)
    assert new_pub.content_json_filepath == converter._build_output_path(new_pub)
    assert mock_cache.call_count == 2


def test_convert_all_skips_batch_when_all_outputs_exist(tmp_path):
    """If every pub already has output on disk, no MinerU subprocess is spawned."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pubs = [_make_pub(f"10.1000/{c}", tmp_path) for c in "AB"]
    converter = MinerUPdfTransformer(publication_list=pubs)
    converter.output_dir = tmp_path
    for pub in pubs:
        _make_md(converter, pub)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run") as mock_run, \
         patch.object(converter, "_cache_result") as mock_cache:
        converter.transform_all()

    mock_run.assert_not_called()
    assert all(pub.content_json_filepath == converter._build_output_path(pub) for pub in pubs)
    assert mock_cache.call_count == 2


def test_convert_all_nonzero_exit_still_collects_outputs(tmp_path):
    """A failed batch is not fatal — publications whose .md exists are still cached."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    ok_pub = _make_pub("10.1000/OK", tmp_path)
    bad_pub = _make_pub("10.1000/BAD", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[ok_pub, bad_pub])
    converter.output_dir = tmp_path

    def fake_run(cmd, **kwargs):
        _make_md(converter, ok_pub)
        return MagicMock(returncode=1, stderr="one task failed")

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result") as mock_cache:
        converter.transform_all()

    assert ok_pub.content_json_filepath == converter._build_output_path(ok_pub)
    assert bad_pub.content_json_filepath is None
    mock_cache.assert_called_once_with(ok_pub)


def test_convert_all_passes_vram_override_when_set(tmp_path):
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pub = _make_pub("10.1000/V", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return MagicMock(returncode=0)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.MINERU_VIRTUAL_VRAM_SIZE", "16"), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    assert captured["env"]["MINERU_VIRTUAL_VRAM_SIZE"] == "16"


def test_convert_all_strips_blank_vram_override(tmp_path, monkeypatch):
    """A blank value in secrets.env must not reach the MinerU subprocess."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    monkeypatch.setenv("MINERU_VIRTUAL_VRAM_SIZE", "")
    pub = _make_pub("10.1000/W", tmp_path)
    converter = MinerUPdfTransformer(publication_list=[pub])
    converter.output_dir = tmp_path

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs["env"]
        return MagicMock(returncode=0)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.MINERU_VIRTUAL_VRAM_SIZE", ""), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", side_effect=fake_run), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    assert "MINERU_VIRTUAL_VRAM_SIZE" not in captured["env"]


def test_convert_all_uses_base_class(tmp_path):
    """transform_all() uses the base class iteration (calls transform2json per pub)."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pubs = [_make_pub("10.1000/X", tmp_path)]
    converter = MinerUPdfTransformer(publication_list=pubs)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU), \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", return_value=MagicMock(returncode=0)), \
         patch.object(converter, "transform2json", return_value=None) as mock_transform, \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    mock_transform.assert_called_once_with(pubs[0])


def test_convert_all_checks_mineru_once(tmp_path):
    """transform_all() calls check_mineru exactly once regardless of publication count."""
    from text_transformation.converters.mineru_pdf_to_md import MinerUPdfTransformer

    pubs = [_make_pub(f"10.1000/{i}", tmp_path) for i in range(3)]
    converter = MinerUPdfTransformer(publication_list=pubs)

    with patch("text_transformation.converters.mineru_pdf_to_md.check_mineru", return_value=FAKE_MINERU) as mock_check, \
         patch("text_transformation.converters.mineru_pdf_to_md.subprocess.run", return_value=MagicMock(returncode=0)), \
         patch.object(converter, "transform2json", return_value=None), \
         patch.object(converter, "_cache_result"):
        converter.transform_all()

    mock_check.assert_called_once()