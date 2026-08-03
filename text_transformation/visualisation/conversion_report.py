"""
Plotly HTML report summarising XML->md and PDF->md conversion outcomes.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import List

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from config import REPORT_DIR
from text_download.basemodels.publication import Publication
from text_download.utils.generics import build_plotly_report

pio.templates.default = "plotly_white"

_GREEN = "#2ECC71"
_RED = "#E74C3C"
_GREY = "#95A5A6"


def _make_conversion_df(
    newly_converted: List[Publication],
    pre_cached: List[Publication],
) -> pd.DataFrame:
    """
    Build a flat DataFrame from newly-converted and pre-cached publications.

    Columns: doi, publisher, year, document_type, status, prev_cached, md_size_kb
    """
    records = []

    for pub in newly_converted:
        success = pub.content_json_filepath is not None
        size_kb = 0.0
        if success:
            try:
                size_kb = pub.content_json_filepath.stat().st_size / 1024
            except OSError:
                logging.warning(f"Could not stat {pub.content_json_filepath} for {pub.doi} -- recording size as 0.")
        records.append({
            "doi": pub.doi,
            "publisher": pub.publisher,
            "year": pub.year,
            "document_type": pub.document_type,
            "status": "Converted" if success else "Failed",
            "prev_cached": False,
            "md_size_kb": size_kb,
        })

    for pub in pre_cached:
        size_kb = 0.0
        if pub.content_json_filepath is not None:
            try:
                size_kb = pub.content_json_filepath.stat().st_size / 1024
            except OSError:
                logging.warning(f"Could not stat {pub.content_json_filepath} for {pub.doi} -- recording size as 0.")
        records.append({
            "doi": pub.doi,
            "publisher": pub.publisher,
            "year": pub.year,
            "document_type": pub.document_type,
            "status": "Pre-cached",
            "prev_cached": True,
            "md_size_kb": size_kb,
        })

    _COLUMNS = ["doi", "publisher", "year", "document_type", "status", "prev_cached", "md_size_kb"]
    if not records:
        return pd.DataFrame(columns=_COLUMNS)
    df = pd.DataFrame(records)
    df["prev_cached"] = df["prev_cached"].astype(object)
    return df


def _add_status_bars(fig: go.Figure, summary: pd.DataFrame, x_col: str) -> None:
    """Add one bar trace per status to fig, using the project colour scheme."""
    color_map = {"Converted": _GREEN, "Failed": _RED, "Pre-cached": _GREY}
    for status in ["Converted", "Failed", "Pre-cached"]:
        subset = summary[summary["status"] == status]
        fig.add_bar(
            x=subset[x_col],
            y=subset["count"],
            name=status,
            marker_color=color_map[status],
        )


def _plt_overall_status(df: pd.DataFrame) -> go.Figure:
    """Grouped bar: XML vs PDF, coloured by Converted / Failed / Pre-cached."""
    summary = (
        df.groupby(["document_type", "status"])["doi"]
        .count()
        .reset_index(name="count")
    )
    fig = go.Figure()
    _add_status_bars(fig, summary, "document_type")
    fig.update_layout(
        title="Overall Conversion Status by Document Type",
        xaxis_title="Document Type",
        yaxis_title="Count",
        barmode="group",
    )
    return fig


def _plt_status_by_publisher(df: pd.DataFrame) -> go.Figure:
    """Grouped bar: publisher on x-axis, Converted / Failed / Pre-cached bars."""
    summary = (
        df.groupby(["publisher", "status"])["doi"]
        .count()
        .reset_index(name="count")
    )
    fig = go.Figure()
    _add_status_bars(fig, summary, "publisher")
    fig.update_layout(
        title="Conversion Status by Publisher",
        xaxis_title="Publisher",
        yaxis_title="Count",
        barmode="group",
    )
    return fig


def _plt_status_by_year(df: pd.DataFrame) -> go.Figure:
    """Grouped bar: year on x-axis, Converted / Failed / Pre-cached bars."""
    summary = (
        df.groupby(["year", "status"])["doi"]
        .count()
        .reset_index(name="count")
        .assign(year=lambda d: d["year"].astype(str))
    )
    fig = go.Figure()
    _add_status_bars(fig, summary, "year")
    fig.update_layout(
        title="Conversion Status by Publication Year",
        xaxis_title="Year",
        yaxis_title="Count",
        barmode="group",
    )
    return fig


def _plt_md_size_distribution(df: pd.DataFrame) -> go.Figure:
    """Box plot of .md file size in KB for successfully converted papers, by document type."""
    success = df[df["status"] == "Converted"]
    fig = go.Figure()
    for doc_type in success["document_type"].unique():
        subset = success[success["document_type"] == doc_type]
        fig.add_box(
            y=subset["md_size_kb"],
            name=str(doc_type),
            boxpoints="outliers",
        )
    fig.update_layout(
        title="Output Markdown File Size Distribution (Successful Conversions)",
        yaxis_title="File Size (KB)",
    )
    if success.empty:
        fig.update_layout(annotations=[dict(text="No successful conversions", showarrow=False, font_size=16)])
    return fig


def _plt_failures_by_publisher(df: pd.DataFrame) -> go.Figure:
    """Horizontal bar: publisher on y-axis, failure count on x-axis, coloured by document type."""
    failures = df[df["status"] == "Failed"]
    summary = (
        failures.groupby(["publisher", "document_type"])["doi"]
        .count()
        .reset_index(name="count")
    )
    fig = go.Figure()
    for doc_type in summary["document_type"].unique():
        subset = summary[summary["document_type"] == doc_type]
        fig.add_bar(
            x=subset["count"],
            y=subset["publisher"],
            name=str(doc_type),
            orientation="h",
        )
    fig.update_layout(
        title="Failed Conversions by Publisher",
        xaxis_title="Count",
        yaxis_title="Publisher",
        barmode="group",
    )
    if failures.empty:
        fig.update_layout(annotations=[dict(text="No failed conversions", showarrow=False, font_size=16)])
    return fig


def _plt_run_breakdown(df: pd.DataFrame) -> go.Figure:
    """Donut chart: Converted / Failed / Pre-cached split across all publications."""
    counts = df["status"].value_counts()
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(),
        values=counts.values.tolist(),
        hole=0.4,
        marker_colors=[
            _GREEN if s == "Converted" else _RED if s == "Failed" else _GREY
            for s in counts.index
        ],
    ))
    fig.update_layout(title="Run Breakdown")
    return fig


def build_conversion_report(
    newly_converted: List[Publication],
    pre_cached: List[Publication],
    out_file: Path | None = None,
) -> None:
    """
    Build and save a Plotly HTML conversion report.

    Parameters
    ----------
    newly_converted : List[Publication]
        Publications processed in this run (controller.needs_conversion after convert_all()).
    pre_cached : List[Publication]
        Publications already converted in a prior run
        (controller.needs_processing + controller.fully_processed).
    out_file : Path | None
        Output path. Defaults to REPORT_DIR/conversion_report_<timestamp>.html.
    """
    df = _make_conversion_df(newly_converted, pre_cached)

    figs = [
        _plt_overall_status(df),
        _plt_status_by_publisher(df),
        _plt_status_by_year(df),
        _plt_md_size_distribution(df),
        _plt_failures_by_publisher(df),
        _plt_run_breakdown(df),
    ]

    if out_file is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        out_file = REPORT_DIR / f"conversion_report_{timestamp}.html"

    build_plotly_report(
        figures=figs,
        title="Text Transformation Conversion Report",
        subtitle=(
            "Summary of XML->md and PDF->md conversion outcomes for this pipeline run. "
            "Includes pass/fail rates by publisher, year, and document type, "
            "plus markdown file size distribution for successful conversions."
        ),
        output_file=out_file,
    )
    logging.info(f"Conversion report saved to {out_file}")