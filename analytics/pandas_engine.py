"""
pandas data pipeline (Unit 4): type conversion, cleaning, missing values,
filtering, indexing, grouping (incl. hierarchical MultiIndex) and merging.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (ALLOCATABLE_FUNDS, CASE_STATUSES, CONTRIBUTION_TYPES, INJURY_LEVELS,
                    SCHEMAS)

NUMERIC_COLUMNS = {
    "donations": ["amount"],
    "allocations": ["amount"],
    "rescue_cases": ["latitude", "longitude", "estimated_cost"],
    "adoption_applications": ["score"],
    "inventory": ["quantity", "reorder_level"],
    "animals": ["age_years"],
}
DATE_COLUMNS = {
    "donations": ["timestamp"],
    "allocations": ["allocated_at"],
    "rescue_cases": ["reported_at", "assigned_at", "updated_at"],
    "adoption_applications": ["submitted_at", "reviewed_at"],
    "users": ["created_at"],
    "animals": ["added_at"],
    "inventory": ["updated_at"],
}


# ======================================================================= cleaning
def typed(name: str, df: pd.DataFrame) -> pd.DataFrame:
    """Turn the text table into proper types. Empty strings become NaN / NaT."""
    out = df.copy().replace({"": np.nan})
    for column in NUMERIC_COLUMNS.get(name, []):
        if column in out:
            out[column] = pd.to_numeric(out[column], errors="coerce")
    for column in DATE_COLUMNS.get(name, []):
        if column in out:
            out[column] = pd.to_datetime(out[column], errors="coerce")
    return out


def missing_value_report(df: pd.DataFrame) -> pd.DataFrame:
    """How many cells are empty in each column."""
    data = df.replace({"": np.nan})
    report = pd.DataFrame({"missing": data.isna().sum(),
                           "percent": (data.isna().mean() * 100).round(1)})
    report.index.name = "column"
    return report.sort_values("missing", ascending=False)


def clean_donations(df: pd.DataFrame, successful_only: bool = True) -> pd.DataFrame:
    """Typed donations without rows that can't be counted (no amount/date, ≤ 0, failed)."""
    data = typed("donations", df)
    data = data.dropna(subset=["amount", "timestamp"])
    data = data[data["amount"] > 0]
    if successful_only:
        data = data[data["status"] == "Success"]
    data["donor_email"] = data["donor_email"].fillna("(not given)")
    data["case_id"] = data["case_id"].fillna("")
    data["month"] = data["timestamp"].dt.to_period("M").dt.to_timestamp()
    return data.sort_values("timestamp")


def clean_allocations(df: pd.DataFrame) -> pd.DataFrame:
    data = typed("allocations", df).dropna(subset=["amount", "allocated_at"])
    data["month"] = data["allocated_at"].dt.to_period("M").dt.to_timestamp()
    return data.sort_values("allocated_at")


def clean_cases(df: pd.DataFrame) -> pd.DataFrame:
    data = typed("rescue_cases", df)
    data["estimated_cost"] = data["estimated_cost"].fillna(0)
    data["status"] = pd.Categorical(data["status"], categories=CASE_STATUSES, ordered=True)
    data["injury_level"] = pd.Categorical(data["injury_level"], categories=INJURY_LEVELS,
                                          ordered=True)
    data["area"] = data["pincode"].astype(str).str[:3]
    data["month"] = data["reported_at"].dt.to_period("M").dt.to_timestamp()
    return data


# ======================================================================= filtering & indexing
def filter_donations(df: pd.DataFrame, start=None, end=None, types: list[str] | None = None,
                     donor_id: str | None = None, min_amount: float | None = None) -> pd.DataFrame:
    """Boolean-mask filtering on an already cleaned donations frame."""
    mask = pd.Series(True, index=df.index)
    if start is not None:
        mask &= df["timestamp"] >= pd.Timestamp(start)
    if end is not None:
        mask &= df["timestamp"] < pd.Timestamp(end) + pd.Timedelta(days=1)
    if types:
        mask &= df["contribution_type"].isin(types)
    if donor_id:
        mask &= df["donor_id"] == donor_id
    if min_amount is not None:
        mask &= df["amount"] >= min_amount
    return df[mask]


def get_transaction(df: pd.DataFrame, transaction_id: str) -> pd.Series | None:
    """Label-based lookup after setting transaction_id as the index."""
    indexed = df.set_index("transaction_id")
    return indexed.loc[transaction_id] if transaction_id in indexed.index else None


# ======================================================================= grouping
def donations_by_type(df: pd.DataFrame) -> pd.DataFrame:
    grouped = df.groupby("contribution_type")["amount"].agg(
        total="sum", donations="count", average="mean", largest="max")
    return grouped.reindex(CONTRIBUTION_TYPES).fillna(0).round(2)


def monthly_donations(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index("timestamp")["amount"].resample("MS").sum()


def monthly_expenditure(alloc: pd.DataFrame) -> pd.Series:
    if alloc.empty:
        return pd.Series(dtype=float)
    return alloc.set_index("allocated_at")["amount"].resample("MS").sum()


def monthly_type_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    """Hierarchical grouping: (month, fund) MultiIndex, then unstacked into a pivot."""
    multi = df.groupby(["month", "contribution_type"])["amount"].agg(["sum", "count"])
    pivot = multi["sum"].unstack("contribution_type").reindex(columns=CONTRIBUTION_TYPES).fillna(0)
    pivot.index = pivot.index.strftime("%b %Y")
    pivot["Total"] = pivot.sum(axis=1)
    return pivot.round(0)


def monthly_type_multiindex(df: pd.DataFrame) -> pd.DataFrame:
    """The raw two-level grouped frame (handy to show MultiIndex in a viva)."""
    data = df.assign(month=df["month"].dt.strftime("%Y-%m"))
    return data.groupby(["month", "contribution_type"])["amount"].agg(
        total="sum", count="count", mean="mean").round(2)


def top_donors(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    return (df.groupby(["donor_id", "donor_name"])["amount"].agg(total="sum", donations="count")
              .sort_values("total", ascending=False).head(n).reset_index())


def utilization_by_purpose(alloc: pd.DataFrame) -> pd.Series:
    return alloc.groupby("purpose")["amount"].sum().sort_values(ascending=False)


def cases_by_status(cases: pd.DataFrame) -> pd.Series:
    return cases["status"].value_counts().reindex(CASE_STATUSES).fillna(0).astype(int)


def cases_by_area_status(cases: pd.DataFrame) -> pd.DataFrame:
    """Two-level index (area, injury level) → number of cases per status."""
    return (cases.groupby(["area", "injury_level"], observed=True)["status"]
                 .value_counts().unstack(fill_value=0)
                 .reindex(columns=CASE_STATUSES, fill_value=0))


# ======================================================================= money overview
def funds_overview(donations_raw: pd.DataFrame, allocations_raw: pd.DataFrame) -> pd.DataFrame:
    """Raised vs allocated vs available for each fund."""
    donations = clean_donations(donations_raw)
    allocations = clean_allocations(allocations_raw)
    raised = donations.groupby("contribution_type")["amount"].sum()
    used = allocations.groupby("source_fund")["amount"].sum()
    overview = pd.DataFrame(index=pd.Index(CONTRIBUTION_TYPES, name="fund"))
    overview["raised"] = raised.reindex(overview.index).fillna(0)
    overview["allocated"] = used.reindex(overview.index).fillna(0)
    # Money given to a specific case is used for that case straight away.
    specific = overview.index == "Specific Medical Case"
    overview.loc[specific, "allocated"] = overview.loc[specific, "raised"]
    overview["available"] = (overview["raised"] - overview["allocated"]).clip(lower=0)
    overview["allocatable"] = overview.index.isin(ALLOCATABLE_FUNDS)
    return overview.round(2)


def case_funding_table(cases_raw: pd.DataFrame, donations_raw: pd.DataFrame,
                       allocations_raw: pd.DataFrame) -> pd.DataFrame:
    """Per case: estimated cost, money given directly, money allocated, gap, % funded."""
    cases = clean_cases(cases_raw)
    donations = clean_donations(donations_raw)
    allocations = clean_allocations(allocations_raw)
    direct = (donations[donations["contribution_type"] == "Specific Medical Case"]
              .groupby("case_id")["amount"].sum().rename("direct_donations"))
    allocated = allocations.groupby("case_id")["amount"].sum().rename("allocated_funds")
    table = (cases.set_index("case_id")[["animal_type", "injury_level", "status", "estimated_cost",
                                         "reported_at"]]
             .join(direct).join(allocated).fillna({"direct_donations": 0, "allocated_funds": 0}))
    table["total_funded"] = table["direct_donations"] + table["allocated_funds"]
    table["gap"] = (table["estimated_cost"] - table["total_funded"]).clip(lower=0)
    cost = table["estimated_cost"].replace(0, np.nan)
    table["percent_funded"] = (table["total_funded"] / cost * 100).clip(upper=100).fillna(100).round(0)
    return table.reset_index().sort_values(["gap", "reported_at"], ascending=[False, True])


def response_times_hours(cases: pd.DataFrame) -> pd.Series:
    """Hours between an SOS being reported and a rescuer taking it."""
    delta = (cases["assigned_at"] - cases["reported_at"]).dropna()
    return (delta.dt.total_seconds() / 3600).rename("hours")


def low_stock(inventory_raw: pd.DataFrame) -> pd.DataFrame:
    inv = typed("inventory", inventory_raw)
    return inv[inv["quantity"] <= inv["reorder_level"]]


def bed_availability(inventory_raw: pd.DataFrame, cases: pd.DataFrame) -> tuple[int, int]:
    """(beds in use, total beds). Total beds come from the 'Kennel beds' inventory row."""
    inv = typed("inventory", inventory_raw)
    beds = inv.loc[inv["item"].str.contains("bed", case=False, na=False), "quantity"]
    total = int(beds.sum()) if not beds.empty else 0
    in_use = int((cases["status"] == "Sheltered/In Treatment").sum())
    return in_use, total


def schema_columns(name: str) -> list[str]:
    return SCHEMAS[name]
