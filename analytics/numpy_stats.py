"""
NumPy statistics and charts (Unit 5: numpy, matplotlib, seaborn).

Charts are built with matplotlib.figure.Figure (not pyplot), so the same
functions work in Streamlit (st.pyplot) and inside PyQt (FigureCanvasQTAgg).
They have transparent backgrounds and take their colours from config.COLORS,
so they sit on the dark (or light) page without a white box around them.
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd
import seaborn as sns
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from config import COLORS, chart_palette, status_colors

# Each Streamlit session runs in its own thread, so the chosen theme is kept per thread.
_theme = threading.local()


def use_theme(colors: dict) -> None:
    """Draw the following charts (in this thread) with this palette – see config.THEMES."""
    _theme.colors = colors


def _c() -> dict:
    return getattr(_theme, "colors", COLORS)


# ======================================================================= numbers
def financial_summary(amounts) -> dict[str, float]:
    """Total, mean, median, standard deviation, spread and percentiles of donations."""
    arr = np.asarray(amounts, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return {k: 0.0 for k in ("count", "total", "mean", "median", "std", "min", "max",
                                 "p25", "p75", "cv")}
    std = float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0
    mean = float(np.mean(arr))
    return {
        "count": float(arr.size),
        "total": float(np.sum(arr)),
        "mean": mean,
        "median": float(np.median(arr)),
        "std": std,
        "min": float(np.min(arr)),
        "max": float(np.max(arr)),
        "p25": float(np.percentile(arr, 25)),
        "p75": float(np.percentile(arr, 75)),
        "cv": float(std / mean * 100) if mean else 0.0,      # coefficient of variation %
    }


def monthly_std(monthly_values) -> float:
    """Standard deviation of month-to-month expenditure (how uneven spending is)."""
    arr = np.asarray(monthly_values, dtype=float)
    return float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0


def growth_rates(monthly_values) -> np.ndarray:
    """Month-on-month growth in % (first month has no previous month)."""
    arr = np.asarray(monthly_values, dtype=float)
    if arr.size < 2:
        return np.array([])
    previous = arr[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rates = np.where(previous > 0, (arr[1:] - previous) / previous * 100, np.nan)
    return np.round(rates, 1)


def recovery_rate(statuses) -> float:
    """(Total recovered / total rescued) × 100. 'Rescued' = taken by a rescuer."""
    arr = np.asarray(statuses, dtype=str)
    rescued = np.count_nonzero(arr != "Reported")
    recovered = np.count_nonzero(arr == "Recovered")
    return float(recovered / rescued * 100) if rescued else 0.0


def response_time_stats(hours) -> dict[str, float]:
    arr = np.asarray(hours, dtype=float)
    arr = arr[~np.isnan(arr)]
    if arr.size == 0:
        return {"mean": 0.0, "median": 0.0, "p90": 0.0, "within_2h": 0.0}
    return {"mean": float(arr.mean()), "median": float(np.median(arr)),
            "p90": float(np.percentile(arr, 90)),
            "within_2h": float(np.mean(arr <= 2) * 100)}


def zscore_outliers(amounts, threshold: float = 3.0) -> np.ndarray:
    """Positions of unusually large/small donations (|z| > threshold) for the audit team."""
    arr = np.asarray(amounts, dtype=float)
    if arr.size < 3 or np.std(arr) == 0:
        return np.array([], dtype=int)
    z = (arr - arr.mean()) / arr.std()
    return np.flatnonzero(np.abs(z) > threshold)


def moving_average(values, window: int = 3) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.size < window:
        return arr
    return np.convolve(arr, np.ones(window) / window, mode="valid")


# ======================================================================= charts
def _rupees(value, _pos=None) -> str:
    if abs(value) >= 100000:
        return f"₹{value / 100000:.1f}L"
    if abs(value) >= 1000:
        return f"₹{value / 1000:.0f}k"
    return f"₹{value:.0f}"


def _style(ax, title: str = "") -> None:
    """Transparent axes, faint gridlines, readable labels in the theme's text colours."""
    c = _c()
    ax.set_facecolor("none")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(c["border"])
    ax.tick_params(colors=c["muted"], labelsize=10, length=0, pad=6)
    ax.grid(axis="y", color=c["border"], alpha=0.7, linewidth=0.8)      # border colour, low opacity
    ax.set_axisbelow(True)
    ax.xaxis.label.set_color(c["muted"])
    ax.yaxis.label.set_color(c["muted"])
    if title:
        ax.set_title(title, loc="left", fontsize=13, fontweight="bold", color=c["text"], pad=14)


def _legend(ax, *args, **kwargs):
    legend = ax.legend(*args, frameon=False, fontsize=10, labelcolor=_c()["text"], **kwargs)
    return legend


def _figure(width: float = 5.6, height: float = 3.5) -> Figure:
    fig = Figure(figsize=(width, height), dpi=110)
    fig.patch.set_alpha(0)                 # no white box behind the chart
    return fig


def _empty(fig: Figure, ax, message: str) -> Figure:
    ax.axis("off")
    ax.text(0.5, 0.5, message, ha="center", va="center", color=_c()["muted"], fontsize=11)
    return fig


def plot_monthly_trend(donations: pd.Series, expenditure: pd.Series) -> Figure:
    """Line chart: monthly donations vs rescue expenditure."""
    fig = _figure()
    ax = fig.add_subplot(111)
    _style(ax, "Donations vs rescue spending")
    if donations.empty and expenditure.empty:
        return _empty(fig, ax, "No money movements yet")
    frame = pd.DataFrame({"Donations": donations, "Spending": expenditure}).fillna(0).sort_index()
    labels = frame.index.strftime("%b %y")
    x = np.arange(len(frame))
    palette, surface = chart_palette(_c()), _c()["surface"]
    ax.plot(x, frame["Donations"], marker="o", lw=2.4, color=palette[0], label="Donations",
            markeredgecolor=surface, markeredgewidth=1.5)
    ax.fill_between(x, frame["Donations"], color=palette[0], alpha=0.14)
    ax.plot(x, frame["Spending"], marker="o", lw=2.4, color=palette[1], label="Rescue spending",
            markeredgecolor=surface, markeredgewidth=1.5)
    ax.fill_between(x, frame["Spending"], color=palette[1], alpha=0.08)
    ax.set_xticks(x, labels)
    ax.yaxis.set_major_formatter(FuncFormatter(_rupees))
    _legend(ax, loc="upper left")
    fig.tight_layout()
    return fig


def plot_fund_utilization(utilization: pd.Series) -> Figure:
    """Donut chart: where allocated money went."""
    fig = _figure(5.6, 3.7)
    ax = fig.add_subplot(111)
    _style(ax, "How allocated funds were used")
    ax.title.set_position((0, 1.08))          # leave room for the outside percentage labels
    if utilization.empty or utilization.sum() == 0:
        return _empty(fig, ax, "No funds allocated yet")
    ax.grid(False)
    c = _c()
    # Percentages sit just outside the ring in the light text colour – light text on the
    # pastel wedges themselves would be too faint to read.
    wedges, _texts, autotexts = ax.pie(
        utilization.values, labels=None, autopct=lambda p: f"{p:.0f}%" if p >= 5 else "",
        startangle=90, counterclock=False, pctdistance=1.17,
        colors=(chart_palette(c) + [c["danger"], c["muted"]])[:len(utilization)],   # 7 distinct colours
        wedgeprops={"width": 0.38, "edgecolor": c["surface"], "linewidth": 2.5})
    for text in autotexts:
        text.set_color(c["text"])
        text.set_fontsize(10)
        text.set_fontweight("bold")
    ax.text(0, 0.08, _rupees(utilization.sum()), ha="center", va="center", fontsize=14,
            fontweight="bold", color=c["text"])
    ax.text(0, -0.17, "allocated", ha="center", va="center", fontsize=10, color=c["muted"])
    _legend(ax, wedges, utilization.index, loc="center left", bbox_to_anchor=(1.0, 0.5))
    ax.axis("equal")
    fig.tight_layout()
    return fig


def plot_case_status(counts: pd.Series) -> Figure:
    """Bar chart: how many cases are at each stage."""
    fig = _figure()
    ax = fig.add_subplot(111)
    _style(ax, "Rescue cases by stage")
    if counts.sum() == 0:
        return _empty(fig, ax, "No rescue cases yet")
    labels = [s.replace("/", "/\n") for s in counts.index]
    stages = status_colors(_c())
    sns.barplot(x=labels, y=counts.values, hue=labels, legend=False, ax=ax, saturation=1,
                palette=[stages.get(s, chart_palette(_c())[0]) for s in counts.index])
    for patch in ax.patches:
        patch.set_alpha(0.9)
    for index, value in enumerate(counts.values):
        ax.text(index, value, f" {int(value)}", ha="center", va="bottom", fontsize=10,
                color=_c()["text"], fontweight="bold")
    ax.set_xlabel("")
    ax.set_ylabel("Cases")
    fig.tight_layout()
    return fig


def plot_donation_distribution(amounts) -> Figure:
    """Histogram (log scale) of donation sizes with mean and median lines."""
    fig = _figure()
    ax = fig.add_subplot(111)
    _style(ax, "Donation sizes")
    arr = np.asarray(amounts, dtype=float)
    if arr.size == 0:
        return _empty(fig, ax, "No donations yet")
    palette = chart_palette(_c())
    sns.histplot(arr, bins=20, log_scale=True, color=palette[2], edgecolor=_c()["surface"], alpha=0.85, ax=ax)
    mean, median = np.mean(arr), np.median(arr)
    top = ax.get_ylim()[1]
    for value, label, color, height, align in (
            (mean, "mean", palette[0], 0.93, "left" if mean >= median else "right"),
            (median, "median", palette[1], 0.80, "right" if mean >= median else "left")):
        ax.axvline(value, color=color, lw=2, ls="--")
        pad = " " if align == "left" else ""
        ax.text(value, top * height, f"{pad}{label} {_rupees(value)}{'' if pad else ' '}", color=color,
                fontsize=10, ha=align, fontweight="bold")
    ax.xaxis.set_major_formatter(FuncFormatter(_rupees))
    ax.set_xlabel("")
    ax.set_ylabel("Donations")
    fig.tight_layout()
    return fig


def plot_funds_by_type(by_type: pd.DataFrame) -> Figure:
    """Horizontal bars: money raised per fund."""
    fig = _figure(6.4, 2.8)
    ax = fig.add_subplot(111)
    _style(ax, "Raised per fund")
    if by_type["total"].sum() == 0:
        return _empty(fig, ax, "No donations yet")
    ax.grid(axis="x", color=_c()["border"], alpha=0.7)
    ax.grid(axis="y", visible=False)
    ax.barh(by_type.index, by_type["total"], color=chart_palette(_c())[:len(by_type)], height=0.55)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(FuncFormatter(_rupees))
    for y, value in enumerate(by_type["total"]):
        ax.text(value, y, f"  {_rupees(value)}", va="center", fontsize=10, color=_c()["text"])
    fig.tight_layout()
    return fig
