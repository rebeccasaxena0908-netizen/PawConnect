"""Small helpers shared by the blueprints."""
from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal

import numpy as np
import pandas as pd


def plain(value):
    """numpy / pandas / Decimal values → things json can write."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return None if pd.isna(value) else value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, Decimal):
        return f"{value:.2f}"                       # money travels as an exact string
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(value) else round(float(value), 2)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def records(df: pd.DataFrame) -> list[dict]:
    """DataFrame → list of JSON-ready dicts."""
    return [{str(k): plain(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


def series_points(series: pd.Series, key: str = "value") -> list[dict]:
    """Monthly pandas Series → [{"month": "2026-05-01", "value": 1234.0}, ...] for charts."""
    return [{"month": pd.Timestamp(index).strftime("%Y-%m-%d"), key: plain(value)}
            for index, value in series.items()]
