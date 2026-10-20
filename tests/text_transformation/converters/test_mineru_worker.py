"""Tests for the MinerU 4 worker. MinerU itself is mocked, so these run without it installed."""
import json
import sys
import types
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from biomarkit.text_transformation.converters import mineru_worker


@pytest.fixture
def fake_mineru(monkeypatch):
    """
    Installs stub mineru modules. parse() returns a result whose save() writes a middle_json.json
    (containing the PDF name, or raises for PDFs named 'bad*'); render_content_list_v2 echoes it into a V2 page.
    """
    parsers = []

    class FakeParseResult:
        def __init__(self, name):
            self.middle_json = {"name": name}

        def save(self, writer):
            out = Path(writer.parent_dir)
            (out / "middle_json.json").write_text(json.dumps(self.middle_json), encoding="utf-8")
            for name in ("markdown.md", "structured_content.json", "model_output.json"):
                (out / name).write_text("{}", encoding="utf-8")
            (out / "images").mkdir(exist_ok=True)
            (out / "images" / "page_0_image_1.jpg").write_bytes(b"\xff")

        @staticmethod
        def from_json(text):
            return FakeParseResult(json.loads(text)["name"])

    class FakeParser:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.parsed = []
            parsers.append(self)

        def parse(self, path, page_range=""):
            assert page_range == "all"
            self.parsed.append(Path(path).name)
            if Path(path).name.startswith("bad"):
                raise ValueError("broken pdf")
            return FakeParseResult(Path(path).name)

    class FakeWriter:
        def __init__(self, parent_dir=""):
            self.parent_dir = parent_dir

    vlm_configs = []

    def fake_vlm_config(**kwargs):
        vlm_configs.append(kwargs)
        return ("vlm", kwargs)

    modules = {
        "mineru": types.ModuleType("mineru"),
        "mineru.config": types.SimpleNamespace(VlmConfig=fake_vlm_config),
        "mineru.parser": types.SimpleNamespace(MinerUParser=FakeParser, ParseResult=FakeParseResult),
        "mineru.parser.writer": types.SimpleNamespace(FileBasedDataWriter=FakeWriter),
        "mineru.render": types.SimpleNamespace(
            render_content_list_v2=lambda middle: [[{"type": "paragraph", "source": middle["name"]}]]
        ),
    }
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return types.SimpleNamespace(parsers=parsers, vlm_configs=vlm_configs)


def _job(tmp_path, names, **overrides):
    items = []
    for name in names:
        pdf = tmp_path / "pdfs" / f"{name}.pdf"
        pdf.parent.mkdir(exist_ok=True)
        pdf.touch()
        items.append({"pdf": str(pdf), "out_dir": str(tmp_path / "out" / name / "auto")})
    return {"tier": "standard", "server_url": "", "api_key": "", "results": str(tmp_path / "results.json"),
            "items": items, **overrides}


def test_one_parser_serves_every_pdf(tmp_path, fake_mineru):
    mineru_worker.run_job(_job(tmp_path, ["a", "b", "c"], tier="basic"))

    assert len(fake_mineru.parsers) == 1
    assert fake_mineru.parsers[0].kwargs["tier"] == "basic"
    assert fake_mineru.parsers[0].parsed == ["a.pdf", "b.pdf", "c.pdf"]


def test_writes_content_list_v2_next_to_saved_result(tmp_path, fake_mineru):
    mineru_worker.run_job(_job(tmp_path, ["paper"]))

    out_dir = tmp_path / "out" / "paper" / "auto"
    content_list = json.loads((out_dir / "paper_content_list_v2.json").read_text(encoding="utf-8"))
    assert content_list == [[{"type": "paragraph", "source": "paper.pdf"}]]
    assert (out_dir / "middle_json.json").exists()


def test_cleanup_keeps_only_content_list_and_images(tmp_path, fake_mineru):
    mineru_worker.run_job(_job(tmp_path, ["paper"], cleanup=True))

    out_dir = tmp_path / "out" / "paper" / "auto"
    assert sorted(p.name for p in out_dir.iterdir()) == ["images", "paper_content_list_v2.json"]
    assert (out_dir / "images" / "page_0_image_1.jpg").exists()


def test_without_cleanup_keeps_all_mineru_outputs(tmp_path, fake_mineru):
    mineru_worker.run_job(_job(tmp_path, ["paper"], cleanup=False))

    names = {p.name for p in (tmp_path / "out" / "paper" / "auto").iterdir()}
    assert {"middle_json.json", "markdown.md", "structured_content.json", "model_output.json",
            "images", "paper_content_list_v2.json"} <= names


def test_failure_on_one_pdf_does_not_stop_the_rest(tmp_path, fake_mineru):
    results = mineru_worker.run_job(_job(tmp_path, ["a", "bad_one", "c"]))

    assert [r["ok"] for r in results] == [True, False, True]
    assert "ValueError: broken pdf" in results[1]["error"]
    assert (tmp_path / "out" / "c" / "auto" / "c_content_list_v2.json").exists()
    assert not (tmp_path / "out" / "bad_one" / "auto" / "bad_one_content_list_v2.json").exists()


def test_results_file_matches_return_value(tmp_path, fake_mineru):
    job = _job(tmp_path, ["a", "bad_b"])
    results = mineru_worker.run_job(job)
    assert json.loads(Path(job["results"]).read_text(encoding="utf-8")) == results


def test_local_vlm_passes_no_vlm_config(tmp_path, fake_mineru):
    mineru_worker.run_job(_job(tmp_path, ["a"]))
    assert fake_mineru.parsers[0].kwargs["vlm_config"] is None
    assert fake_mineru.vlm_configs == []


def test_remote_vlm_builds_vlm_config(tmp_path, fake_mineru):
    mineru_worker.run_job(_job(tmp_path, ["a"], server_url="http://vlm:30000", api_key="k"))
    assert fake_mineru.vlm_configs == [{"server_url": "http://vlm:30000", "api_key": "k"}]
    assert fake_mineru.parsers[0].kwargs["vlm_config"] == ("vlm", {"server_url": "http://vlm:30000", "api_key": "k"})


def test_main_reads_job_file(tmp_path, fake_mineru):
    job = _job(tmp_path, ["a"])
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")

    mineru_worker.main(str(job_path))

    assert json.loads(Path(job["results"]).read_text(encoding="utf-8"))[0]["ok"] is True
