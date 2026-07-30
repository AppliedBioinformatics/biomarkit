import plotly.io as pio
from typing import List
from text_extraction.basemodels.publication import Publication
import pandas as pd
import plotly.graph_objects as go
from text_extraction.filter.publisher_map import publisher_map

# Set plotly default theme.
pio.templates.default = "plotly_white"

def _make_publication_df(publication_list: List[Publication], prev_cached: bool = False) -> pd.DataFrame:
    """
    Converts a list of Publication objects into a Pandas dataframe with the following columns:
    'doi', 'year', 'publisher', 'publication_filepath', 'title', 'is_cached'.

    Parameters
    ----------
    publication_list: List[Publication]

    Returns
    -------
    pd.DataFrame
    """
    publications = publication_list
    records = []
    for pub in publications:
        records.append({
            "doi": pub.doi,
            "year": pub.year,
            "publisher": pub.publisher,
            "publication_filepath": pub.publication_filepath,
            "title": pub.title,
            "is_cached": pub.is_cached,
            "prev_cached": True if prev_cached else False
        })

    return pd.DataFrame(records)

def _plt_total_successfull_downloads(df: pd.DataFrame) -> go.Figure:
    prev_cached = (df["prev_cached"] == True).sum()
    newly_cached = ((df["prev_cached"] == False) & (df["is_cached"] == True)).sum()
    still_uncached = ((df["prev_cached"] == False) & (df["is_cached"] == False)).sum()

    categories = ["Previously Cached",
                  "Download Successful",
                  "Download Failed"]

    values = [prev_cached,
              newly_cached,
              still_uncached]

    colors = ["#95A5A6",  # grey
              "#2ECC71",  # green
              "#E74C3C"]  # red

    fig = go.Figure()

    fig.add_bar(
        x=categories,
        y=values,
        marker_color=colors,
    )

    fig.update_layout(
        title="Cache Status Overview",
        xaxis_title="Category",
        yaxis_title="Count",
    )

    return fig

def _plt_total_downloads_by_api(df: pd.DataFrame) -> go.Figure:
    filtered = df[df["prev_cached"] == False]
    filtered = filtered[filtered["publisher"].isin(publisher_map.keys())]

    # Count stats.
    cached_counts = (
        filtered.groupby("publisher")["is_cached"].sum().rename("cached_success")
    )

    total_counts = filtered.groupby("publisher")["is_cached"].count()
    uncached_counts = (total_counts - cached_counts).rename("uncached_fail")
    summary = pd.concat([cached_counts, uncached_counts], axis=1).fillna(0)

    fig = go.Figure()

    fig.add_bar(
        x=summary.index,
        y=summary["cached_success"],
        name="Successful",
        marker_color="#2ECC71"
    )

    fig.add_bar(
        x=summary.index,
        y=summary["uncached_fail"],
        name="Unsuccessful",
    )

    fig.update_layout(
        title="Total downloads per publisher group/API.",
        barmode="group",
        xaxis_title="Publisher",
        yaxis_title="Count",
    )

    return fig

def _plt_total_downloads_inc_cache(df: pd.DataFrame) -> go.Figure:
    filtered = df[df["publisher"].isin(publisher_map.keys())]

    previously_cached = (
        filtered[filtered["prev_cached"] == True]
        .groupby("publisher")["prev_cached"]
        .count()
        .rename("previously_cached")
    )

    newly_cached = (
        filtered[(filtered["prev_cached"] == False) & (filtered["is_cached"] == True)]
        .groupby("publisher")["is_cached"]
        .count()
        .rename("newly_cached")
    )

    still_uncached = (
        filtered[(filtered["prev_cached"] == False) & (filtered["is_cached"] == False)]
        .groupby("publisher")["is_cached"]
        .count()
        .rename("still_uncached")
    )

    # Combine into one table
    summary = pd.concat([previously_cached, newly_cached, still_uncached], axis=1).fillna(0)

    fig = go.Figure()

    fig.add_bar(
        x=summary.index,
        y=summary["previously_cached"],
        name="Found in cache",
        marker_color="#95A5A6",  # grey
    )

    fig.add_bar(
        x=summary.index,
        y=summary["newly_cached"],
        name="Downloaded successfully",
        marker_color="#2ECC71",  # green
    )

    fig.add_bar(
        x=summary.index,
        y=summary["still_uncached"],
        name="Not downloaded",
        marker_color="#E74C3C",  # red
    )

    fig.update_layout(
        title="Cache Status per Publisher (Including Historical Cached Rows)",
        barmode="group",
        xaxis_title="Publisher",
        yaxis_title="Count",
    )

    return fig

def _plt_total_downloads_by_year(df: pd.DataFrame) -> go.Figure:
    year_counts = df.groupby("year")["doi"].count()

    fig = go.Figure()

    fig.add_bar(
        x=year_counts.index.astype(str),
        y=year_counts.values,
        name="Publications",
    )

    fig.update_layout(
        title="Number of Publications by Year",
        xaxis_title="Year",
        yaxis_title="Count",
    )

    return fig

