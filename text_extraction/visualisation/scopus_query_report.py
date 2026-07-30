from config import PLOTLY_THEME
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
from text_extraction.utils.generics import truncate_labels

# Set plotly default theme.
pio.templates.default = "plotly_white"

def _plt_raw_publisher_frequency(df: pd.DataFrame, top_k:int=50) -> go.Figure:

    # Count rows per publisher
    counts = df["Publisher"].value_counts().rename_axis("Publisher").reset_index(name="Count")
    counts = counts.sort_values("Count", ascending=False).reset_index(drop=True)

    # Keep top_k, combine rest
    if len(counts) <= top_k:
        plot_df = counts.copy()
    else:
        top = counts.iloc[:top_k].copy()
        rest = counts.iloc[top_k:]
        other_row = pd.DataFrame({
            "Publisher": ["Other publishers"],
            "Count": [rest["Count"].sum()]
        })
        plot_df = pd.concat([top, other_row], ignore_index=True)

    # Truncate labels
    plot_df["Publisher"] = plot_df["Publisher"].astype(str).map(truncate_labels)

    # Sort again for left-to-right largest → smallest
    plot_df = plot_df.sort_values("Count", ascending=False).reset_index(drop=True)

    fig = px.bar(
        plot_df,
        x="Publisher",
        y="Count",
        title=f"Top {min(top_k, len(counts))} Publishers (ungrouped).",
        labels={"Publisher": "Publisher", "Count": "Number of Rows"},
    )

    fig.update_layout(xaxis_tickangle=-45, yaxis_title="Number of Publications", template=PLOTLY_THEME)
    return fig

def _plt_publisher_group_frequency(df: pd.DataFrame, top_k:int=50) -> go.Figure:
    # Count rows per publisher
    counts = df["PublisherGroup"].value_counts().rename_axis("PublisherGroup").reset_index(name="Count")
    counts = counts.sort_values("Count", ascending=False).reset_index(drop=True)

    # Keep top_k, combine rest
    if len(counts) <= top_k:
        plot_df = counts.copy()
        has_other = False
    else:
        top = counts.iloc[:top_k].copy()
        rest = counts.iloc[top_k:]
        other_row = pd.DataFrame({
            "PublisherGroup": ["Other"],
            "Count": [rest["Count"].sum()]
        })
        plot_df = pd.concat([top, other_row], ignore_index=True)
        has_other = True

    # Truncate labels
    plot_df["PublisherGroup"] = plot_df["PublisherGroup"].astype(str).map(truncate_labels)

    # --- KEY PART: sort everything except "Other", then append "Other" ---
    if has_other:
        non_other = plot_df[plot_df["PublisherGroup"] != "Other"].sort_values("Count", ascending=False)
        other = plot_df[plot_df["PublisherGroup"] == "Other"]
        plot_df = pd.concat([non_other, other], ignore_index=True)
    else:
        plot_df = plot_df.sort_values("Count", ascending=False).reset_index(drop=True)

    fig = px.bar(
        plot_df,
        x="PublisherGroup",
        y="Count",
        title=f"Top {min(top_k, len(counts))} Publishers - Grouped by API.",
        labels={"PublisherGroup": "Publisher Group", "Count": "Number of Rows"},
    )

    fig.update_layout(
        xaxis_tickangle=-45,
        yaxis_title="Number of Publications",
        template=PLOTLY_THEME
    )

    return fig

def _plt_cumulative_frequency_of_publishers(df: pd.DataFrame, top_k:int=50) -> go.Figure:
    # Count rows
    counts = (
        df["PublisherGroup"]
        .value_counts()
        .rename_axis("PublisherGroup")
        .reset_index(name="Count")
        .sort_values("Count", ascending=False)
        .reset_index(drop=True)
    )

    # Keep only top_k
    if len(counts) > top_k:
        counts = counts.iloc[:top_k].copy()

    # Remove any literal "Other"
    counts = counts[counts["PublisherGroup"] != "Other"].copy()

    # Cumulative percentage
    total = counts["Count"].sum()
    counts["CumulativePercent"] = counts["Count"].cumsum() / total * 100

    # Color thresholds
    def assign_color(pct: float) -> str:
        if pct > 80:
            return "green"
        elif pct > 50:
            return "orange"
        elif pct > 20:
            return "red"
        else:
            return "black"

    counts["Color"] = counts["CumulativePercent"].apply(assign_color)

    # Truncate labels
    counts["PublisherGroup"] = counts["PublisherGroup"].astype(str).map(truncate_labels)

    fig = px.bar(
        counts,
        x="PublisherGroup",
        y="CumulativePercent",
        color="Color",
        color_discrete_map="identity",  # use exact colors
        title="Cumulative Percentage of Publisher Groups in Corpus",
        labels={"PublisherGroup": "Publisher Group", "CumulativePercent": "Cumulative %"},
    )

    fig.update_layout(
        yaxis=dict(ticksuffix="%", range=[0, 100]),
        xaxis_tickangle=-45,
        template=PLOTLY_THEME,
        showlegend=False,
    )

    return fig

