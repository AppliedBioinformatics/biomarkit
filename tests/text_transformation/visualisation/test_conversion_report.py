import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import plotly.graph_objects as go
from text_extraction.basemodels.publication import Publication


def _make_pub(doi: str, tmp_path: Path, doc_type: str = "PDF",
              publisher: str = "springer", year: int = 2023,
              raw_md: Path | None = None) -> Publication:
    pub_file = tmp_path / f"{doi.replace('/', '_')}.{'pdf' if doc_type == 'PDF' else 'xml'}"
    pub_file.touch()
    md = None
    if raw_md is not None:
        raw_md.touch()
        md = raw_md
    return Publication(
        doi=doi, title="Test", publisher=publisher, year=year,
        document_type=doc_type,
        publication_filepath=pub_file,
        content_json_filepath=md,
    )


def test_make_conversion_df_newly_converted_success(tmp_path):
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    md = tmp_path / "out.md"
    pub = _make_pub("10.1000/A", tmp_path, raw_md=md)
    df = _make_conversion_df(newly_converted=[pub], pre_cached=[])
    assert len(df) == 1
    assert df.iloc[0]["status"] == "Converted"
    assert df.iloc[0]["prev_cached"] is False


def test_make_conversion_df_newly_converted_failed(tmp_path):
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    pub = _make_pub("10.1000/B", tmp_path)
    df = _make_conversion_df(newly_converted=[pub], pre_cached=[])
    assert df.iloc[0]["status"] == "Failed"


def test_make_conversion_df_pre_cached(tmp_path):
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    md = tmp_path / "cached.md"
    pub = _make_pub("10.1000/C", tmp_path, raw_md=md)
    df = _make_conversion_df(newly_converted=[], pre_cached=[pub])
    assert df.iloc[0]["status"] == "Pre-cached"
    assert df.iloc[0]["prev_cached"] is True


def test_make_conversion_df_columns(tmp_path):
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    pub = _make_pub("10.1000/D", tmp_path)
    df = _make_conversion_df(newly_converted=[pub], pre_cached=[])
    expected_cols = {"doi", "publisher", "year", "document_type", "status",
                     "prev_cached", "md_size_kb"}
    assert expected_cols.issubset(set(df.columns))


def test_make_conversion_df_md_size_kb_populated_for_success(tmp_path):
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    md = tmp_path / "out.md"
    md.write_text("hello world")
    pub = _make_pub("10.1000/E", tmp_path, raw_md=md)
    df = _make_conversion_df(newly_converted=[pub], pre_cached=[])
    assert df.iloc[0]["md_size_kb"] > 0


def test_make_conversion_df_md_size_kb_zero_for_failure(tmp_path):
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    pub = _make_pub("10.1000/F", tmp_path)
    df = _make_conversion_df(newly_converted=[pub], pre_cached=[])
    assert df.iloc[0]["md_size_kb"] == 0.0


def test_make_conversion_df_empty_inputs():
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    df = _make_conversion_df(newly_converted=[], pre_cached=[])
    assert len(df) == 0


# ---------------------------------------------------------------------------
# Helpers shared by plot tests
# ---------------------------------------------------------------------------

def _make_df(tmp_path):
    """Returns a small mixed DataFrame for plot testing."""
    from text_transformation.visualisation.conversion_report import _make_conversion_df

    md1 = tmp_path / "a.md"
    md1.write_text("x" * 1000)
    md2 = tmp_path / "b.md"
    md2.write_text("x" * 500)

    newly = [
        _make_pub("10.1000/G", tmp_path, doc_type="PDF", publisher="springer", year=2022, raw_md=md1),
        _make_pub("10.1000/H", tmp_path, doc_type="PDF", publisher="unpaywall", year=2023),  # fail
        _make_pub("10.1000/I", tmp_path, doc_type="XML", publisher="elsevier", year=2022, raw_md=md2),
    ]
    cached = [
        _make_pub("10.1000/J", tmp_path, doc_type="PDF", publisher="springer", year=2021, raw_md=tmp_path / "c.md"),
    ]
    return _make_conversion_df(newly_converted=newly, pre_cached=cached)


def test_plt_overall_status_returns_figure(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_overall_status
    df = _make_df(tmp_path)
    fig = _plt_overall_status(df)
    assert isinstance(fig, go.Figure)
    assert fig.layout.barmode == "group"
    assert len(fig.data) == 3  # one trace per status


def test_plt_status_by_publisher_returns_figure(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_status_by_publisher
    df = _make_df(tmp_path)
    fig = _plt_status_by_publisher(df)
    assert isinstance(fig, go.Figure)
    assert fig.layout.barmode == "group"
    assert len(fig.data) == 3


def test_plt_status_by_year_returns_figure(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_status_by_year
    df = _make_df(tmp_path)
    fig = _plt_status_by_year(df)
    assert isinstance(fig, go.Figure)
    assert fig.layout.barmode == "group"
    assert len(fig.data) == 3


def test_plt_md_size_distribution_returns_figure(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_md_size_distribution
    df = _make_df(tmp_path)
    fig = _plt_md_size_distribution(df)
    assert isinstance(fig, go.Figure)
    # 2 successful conversions (PDF + XML) → 2 box traces
    assert len(fig.data) == 2


def test_plt_md_size_distribution_blank_when_no_successes(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_md_size_distribution
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    pub = _make_pub("10.1000/X", tmp_path)  # no raw_md → Failed
    df = _make_conversion_df(newly_converted=[pub], pre_cached=[])
    fig = _plt_md_size_distribution(df)
    assert len(fig.data) == 0
    assert any("No successful" in (a.text or "") for a in fig.layout.annotations)


def test_plt_failures_by_publisher_returns_figure(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_failures_by_publisher
    df = _make_df(tmp_path)
    fig = _plt_failures_by_publisher(df)
    assert isinstance(fig, go.Figure)
    # 1 failed PDF (unpaywall) → 1 doc_type → 1 trace
    assert len(fig.data) == 1
    assert fig.data[0].orientation == "h"


def test_plt_failures_by_publisher_blank_when_no_failures(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_failures_by_publisher
    from text_transformation.visualisation.conversion_report import _make_conversion_df
    md = tmp_path / "out.md"
    md.write_text("x")
    pub = _make_pub("10.1000/Y", tmp_path, raw_md=md)
    df = _make_conversion_df(newly_converted=[pub], pre_cached=[])
    fig = _plt_failures_by_publisher(df)
    assert len(fig.data) == 0
    assert any("No failed" in (a.text or "") for a in fig.layout.annotations)


def test_plt_run_breakdown_returns_figure(tmp_path):
    from text_transformation.visualisation.conversion_report import _plt_run_breakdown
    df = _make_df(tmp_path)
    fig = _plt_run_breakdown(df)
    assert isinstance(fig, go.Figure)
    assert fig.data[0].hole == 0.4
    assert set(fig.data[0].labels) == {"Converted", "Failed", "Pre-cached"}


# ---------------------------------------------------------------------------
# build_conversion_report — integration
# ---------------------------------------------------------------------------

def test_build_conversion_report_creates_html_file(tmp_path):
    from text_transformation.visualisation.conversion_report import build_conversion_report

    md1 = tmp_path / "a.md"
    md1.write_text("hello")
    pub_converted = _make_pub("10.1000/K", tmp_path, raw_md=md1)
    pub_failed = _make_pub("10.1000/L", tmp_path)

    out_file = tmp_path / "report.html"
    with patch("text_transformation.visualisation.conversion_report.REPORT_DIR", tmp_path):
        build_conversion_report(
            newly_converted=[pub_converted, pub_failed],
            pre_cached=[],
            out_file=out_file,
        )

    assert out_file.exists()
    content = out_file.read_text()
    assert "<html" in content


def test_build_conversion_report_default_filename(tmp_path):
    from text_transformation.visualisation.conversion_report import build_conversion_report

    with patch("text_transformation.visualisation.conversion_report.REPORT_DIR", tmp_path):
        build_conversion_report(newly_converted=[], pre_cached=[])

    html_files = list(tmp_path.glob("conversion_report_*.html"))
    assert len(html_files) == 1