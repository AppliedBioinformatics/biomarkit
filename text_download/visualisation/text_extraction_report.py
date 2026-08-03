import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import plotly.io as pio

from config import REPORT_DIR
from text_download.basemodels.publication import Publication
from text_download.utils.generics import build_plotly_report
from text_download.visualisation.scopus_query_report import (
    _plt_raw_publisher_frequency,
    _plt_publisher_group_frequency,
    _plt_cumulative_frequency_of_publishers,
)
from text_download.visualisation.download_report import (
    _make_publication_df,
    _plt_total_successfull_downloads,
    _plt_total_downloads_by_api,
    _plt_total_downloads_inc_cache,
    _plt_total_downloads_by_year,
)

pio.templates.default = "plotly_white"


def build_text_download_report(
    df: pd.DataFrame,
    downloaded_pubs: List[Publication],
    cached_pubs: List[Publication],
    out_file: Path = None,
    timings: Optional[Dict[str, float]] = None,
):
    """
    Builds a single combined HTML report for the text-extraction pipeline.

    Section 1 — Scopus Input Summary (3 charts):
      - Top publishers (ungrouped)
      - Publishers grouped by API
      - Cumulative percentage of publisher groups

    Section 2 — Download Results (4 charts):
      - Cache status overview
      - Downloads per publisher group / API
      - Cache status per publisher (including historical cache)
      - Publications by year

    Parameters
    ----------
    df : pd.DataFrame
        Filtered Scopus DataFrame (must include "Publisher" and "PublisherGroup" columns).
    downloaded_pubs : List[Publication]
        Publications from the current download attempt.
    cached_pubs : List[Publication]
        Publications that were already in the cache before this run.
    out_file : Path, optional
        Output filename. Defaults to text_download_report_<timestamp>.html.
    timings : Dict[str, float], optional
        Timing metrics (in seconds) to display in the report, keyed by:
        "opensource", "other_apis" and "total". Omitted from the report when None.
    """

    logging.info("Building combined text-extraction report.")

    # --- Section 1: Scopus input summary ---
    scopus_figs = [
        _plt_raw_publisher_frequency(df=df),
        _plt_publisher_group_frequency(df=df),
        _plt_cumulative_frequency_of_publishers(df=df),
    ]

    # --- Section 2: Download results ---
    download_df = _make_publication_df(publication_list=downloaded_pubs, prev_cached=False)
    if cached_pubs:
        cached_df = _make_publication_df(publication_list=cached_pubs, prev_cached=True)
        download_df = pd.concat([download_df, cached_df], ignore_index=True)

    download_figs = [
        _plt_total_successfull_downloads(df=download_df),
        _plt_total_downloads_by_api(df=download_df),
        _plt_total_downloads_inc_cache(df=download_df),
        _plt_total_downloads_by_year(df=download_df),
    ]

    # Combine all figures.
    all_figures = scopus_figs + download_figs

    # --- Optional timing metrics section ---
    html_sections = []
    if timings:
        html_sections.append(_timings_html(timings))

    title = "Text Extraction Report"
    subtitle = (
        "This report summarises the Scopus input query and the full-text download results. "
        "The first section shows publisher frequency distributions from the filtered Scopus CSV. "
        "The second section shows download success rates, cache status, and year distribution."
    )

    if out_file is None:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        out_file = f"text_download_report_{timestamp}.html"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = REPORT_DIR / out_file
    build_plotly_report(
        figures=all_figures, title=title, subtitle=subtitle, output_file=output_file,
        html_sections=html_sections,
    )
    logging.info(f"Combined text-extraction report saved to {output_file}.")


def _timings_html(timings: Dict[str, float]) -> str:
    """Render the extract_text timing metrics as an HTML table for the report."""
    rows = [
        ("Open-source downloads (preprints + Unpaywall)", timings.get("opensource")),
        ("Other API queries", timings.get("other_apis")),
        ("Total", timings.get("total")),
    ]
    row_html = "".join(
        f"<tr><td>{label}</td><td style='text-align:right'>{value:.2f} s</td></tr>"
        for label, value in rows if value is not None
    )
    return (
        "<h2 style='margin-top:0'>Timing Metrics</h2>"
        "<table style='border-collapse:collapse;width:100%'>"
        "<thead><tr>"
        "<th style='text-align:left;border-bottom:1px solid #ddd;padding:6px'>Stage</th>"
        "<th style='text-align:right;border-bottom:1px solid #ddd;padding:6px'>Time</th>"
        "</tr></thead>"
        f"<tbody>{row_html}</tbody></table>"
    )
