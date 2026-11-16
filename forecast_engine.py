"""
BNH Sales Forecasting Engine
============================
Single source of truth for every calculation in the forecasting tool.
The web app (app.py), the command line (run_forecast.py) and the Excel report
all use this module, so a rule changed here changes everywhere.

Method (same as the original scripts):
    Monthly run rate     = YTD sales / months completed
    Projected full year  = run rate x 12
    Required run rate    = (annual target - YTD sales) / months remaining
    Status               = On Track (>= 100%) / Watch (>= 90%) / Action Required

All money values are in Rs Lakh. The financial year runs April to March.
"""

from __future__ import annotations

import io
import re
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "Month",
    "Region",
    "Channel",
    "Previous_Year_Sales_Lakh",
    "Current_Sales_Lakh",
    "Target_Lakh",
]
NUMERIC_COLUMNS = REQUIRED_COLUMNS[3:]

ON_TRACK_PCT = 100.0
WATCH_PCT = 90.0

STATUS_ON_TRACK = "On Track"
STATUS_WATCH = "Watch"
STATUS_ACTION = "Action Required"
STATUS_NO_DATA = "No Data"

_MONTH_FORMATS = [
    "%b-%y", "%b-%Y", "%B-%y", "%B-%Y", "%b %y", "%b %Y", "%B %Y",
    "%d-%b-%y", "%d-%b-%Y", "%Y-%m", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y",
    "%d/%m/%y",
]


class DataValidationError(Exception):
    """The input file cannot be trusted. The message is written for a business user."""


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------

def status_for(pct) -> str:
    if pct is None or pd.isna(pct):
        return STATUS_NO_DATA
    if pct >= ON_TRACK_PCT:
        return STATUS_ON_TRACK
    if pct >= WATCH_PCT:
        return STATUS_WATCH
    return STATUS_ACTION


def month_label(ts) -> str:
    return pd.Timestamp(ts).strftime("%b-%y")


def fiscal_year_months(fy_start_year: int) -> list:
    return list(pd.date_range(f"{fy_start_year}-04-01", periods=12, freq="MS"))


def _pct(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    return numerator / denominator.replace(0, np.nan) * 100


def _safe_pct(numerator: float, denominator: float) -> float:
    return float("nan") if not denominator else numerator / denominator * 100


def _sum_keep_nan(s: pd.Series) -> float:
    return s.sum(min_count=1)


def _to_number(series: pd.Series) -> pd.Series:
    """Turn '1,234.5', '₹ 1,234', '(50)' into numbers. Blanks become NaN."""
    s = series.astype("string").str.strip()
    s = s.str.replace(r"[₹,\s]", "", regex=True)
    s = s.str.replace(r"^\((.*)\)$", r"-\1", regex=True)
    s = s.mask(s.isin(["", "-", "—"]))
    converted = pd.to_numeric(s, errors="coerce")
    arr = converted.to_numpy(dtype="float64", na_value=np.nan)
    return pd.Series(arr, index=series.index)


def _parse_months(series: pd.Series) -> pd.Series:
    cleaned = series.astype(str).str.strip()
    best, best_ok = None, -1
    for fmt in _MONTH_FORMATS:
        parsed = pd.to_datetime(cleaned, format=fmt, errors="coerce")
        ok = int(parsed.notna().sum())
        if ok == len(cleaned):
            return parsed.dt.to_period("M").dt.to_timestamp()
        if ok > best_ok:
            best, best_ok = parsed, ok
    bad = cleaned[best.isna()].unique()[:5]
    raise DataValidationError(
        "Could not read the Month column. Use a format like Apr-26. "
        "Unreadable values: " + ", ".join(map(str, bad)) + "."
    )


def _coerce_month(value) -> pd.Timestamp:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.Timestamp(value).to_period("M").to_timestamp()
    return _parse_months(pd.Series([str(value)])).iloc[0]


# --------------------------------------------------------------------------
# Loading and cleaning
# --------------------------------------------------------------------------

@dataclass
class SalesData:
    df: pd.DataFrame
    fy_start_year: int
    notes: list = field(default_factory=list)

    @property
    def fy_label(self) -> str:
        return f"FY {self.fy_start_year}-{str(self.fy_start_year + 1)[-2:]}"

    @property
    def months(self) -> list:
        return fiscal_year_months(self.fy_start_year)

    @property
    def target_month_count(self) -> int:
        return int(self.df.loc[self.df["Target_Lakh"].notna(), "Month_Start"].nunique())

    @property
    def channels(self) -> list:
        return sorted(self.df["Channel"].unique())

    @property
    def regions(self) -> list:
        return sorted(self.df["Region"].unique())

    @property
    def months_with_sales(self) -> list:
        by_month = self.df.groupby("Month_Start")["Current_Sales_Lakh"].sum(min_count=1)
        return [m for m in self.months if by_month.get(m, 0) and by_month.get(m, 0) > 0]


def read_sales_csv(source) -> pd.DataFrame:
    """Read a CSV from a path or an uploaded file object, tolerating Excel's encodings."""
    if hasattr(source, "read"):
        raw = source.read()
    else:
        with open(source, "rb") as fh:
            raw = fh.read()
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    else:
        text = raw
    try:
        return pd.read_csv(io.StringIO(text), dtype=str)
    except Exception as exc:  # unreadable or empty file
        raise DataValidationError(f"The file could not be read as a CSV: {exc}") from exc


def clean_sales_data(raw: pd.DataFrame) -> SalesData:
    notes: list = []
    df = raw.copy()
    df.index = df.index + 2  # row numbers as seen in the CSV (row 1 is the header)

    def key(c):
        return re.sub(r"[\s_]+", "_", str(c).strip().lower())

    lookup = {key(c): c for c in df.columns}
    missing = [c for c in REQUIRED_COLUMNS if key(c) not in lookup]
    if missing:
        raise DataValidationError(
            "These columns are missing from the file: " + ", ".join(missing)
            + ". Expected columns: " + ", ".join(REQUIRED_COLUMNS) + "."
        )
    df = df[[lookup[key(c)] for c in REQUIRED_COLUMNS]].copy()
    df.columns = REQUIRED_COLUMNS
    df = df.dropna(how="all")

    # Month / Region / Channel must be present
    keys = df[["Month", "Region", "Channel"]].astype("string")
    keys = keys.apply(lambda s: s.str.strip()).fillna("")
    blank = (keys == "").any(axis=1)
    if blank.any():
        notes.append(
            f"{int(blank.sum())} row(s) skipped because Month, Region or Channel is blank "
            f"(first one: row {blank[blank].index[0]})."
        )
    df, keys = df[~blank].copy(), keys[~blank]
    if df.empty:
        raise DataValidationError("The file has no usable rows.")
    df[["Month", "Region", "Channel"]] = keys

    # One spelling per Region / Channel (GT, gt, Gt -> first spelling seen)
    for col in ["Region", "Channel"]:
        canon: dict = {}
        mapped = df[col].map(lambda v: canon.setdefault(v.casefold(), v))
        if (mapped != df[col]).any():
            notes.append(f"{col} names that differed only by upper/lower case were merged.")
        df[col] = mapped

    # Numbers
    problems = []
    for col in NUMERIC_COLUMNS:
        original = df[col]
        converted = _to_number(original)
        blank_like = original.isna() | original.astype("string").str.strip().isin(["", "-", "—"])
        bad = ~blank_like & converted.isna()
        if bad.any():
            rows = ", ".join(str(i) for i in bad[bad].index[:5])
            problems.append(f"{col}: not a number in row(s) {rows}")
        df[col] = converted
        negatives = int((converted < 0).sum())
        if negatives:
            notes.append(f"{negatives} negative value(s) in {col}; please confirm they are correct.")
    if problems:
        raise DataValidationError("Some values are not numbers - " + "; ".join(problems) + ".")

    # Months and financial year
    df["Month_Start"] = _parse_months(df["Month"])
    fy = df["Month_Start"].apply(lambda d: d.year if d.month >= 4 else d.year - 1)
    latest_fy = int(fy.max())
    if fy.nunique() > 1:
        dropped = int((fy != latest_fy).sum())
        notes.append(
            f"The file spans more than one financial year. Only FY {latest_fy}-{str(latest_fy + 1)[-2:]} "
            f"is analysed; {dropped} earlier row(s) were ignored."
        )
        df = df[fy == latest_fy].copy()

    # Duplicate Month + Region + Channel rows are added together, with a warning
    dup = df.duplicated(["Month_Start", "Region", "Channel"], keep=False)
    if dup.any():
        notes.append(
            f"{int(dup.sum())} rows share the same Month + Region + Channel and were added together. "
            "Check that the export does not contain the same data twice."
        )
    df = df.groupby(["Month_Start", "Region", "Channel"], as_index=False).agg(
        {c: _sum_keep_nan for c in NUMERIC_COLUMNS}
    )
    df["Month"] = df["Month_Start"].dt.strftime("%b-%y")
    df = df.sort_values(["Month_Start", "Region", "Channel"]).reset_index(drop=True)
    df = df[["Month", "Month_Start", "Region", "Channel"] + NUMERIC_COLUMNS]
    return SalesData(df=df, fy_start_year=latest_fy, notes=notes)


def load_sales_data(source) -> SalesData:
    return clean_sales_data(read_sales_csv(source))


def detect_as_of_month(df: pd.DataFrame, today: Optional[date] = None):
    """Latest month with sales. If that month is still running, use the one before it."""
    today = today or date.today()
    by_month = df.groupby("Month_Start")["Current_Sales_Lakh"].sum(min_count=1)
    by_month = by_month[by_month.fillna(0) > 0]
    if by_month.empty:
        raise DataValidationError("No sales were found in Current_Sales_Lakh.")
    last = by_month.index.max()
    note = None
    still_running = (
        last.year == today.year
        and last.month == today.month
        and today.day < monthrange(today.year, today.month)[1]
    )
    if still_running:
        earlier = by_month.index[by_month.index < last]
        if len(earlier):
            used = earlier.max()
            note = (
                f"{month_label(last)} has sales but the month is still running, so the forecast is "
                f"as of {month_label(used)}. Pick {month_label(last)} manually if it is complete."
            )
            last = used
    return last, note


# --------------------------------------------------------------------------
# Forecast
# --------------------------------------------------------------------------

@dataclass
class ScenarioConfig:
    channel: Optional[str] = None  # None = channel with the largest YTD gap
    region: Optional[str] = None   # None = region with the largest YTD gap
    cases: dict = field(default_factory=lambda: {
        "BASE": (0.0, 0.0),
        "UPSIDE": (10.0, 10.0),
        "STRETCH": (15.0, 15.0),
    })  # name -> (channel uplift %, region uplift %)


@dataclass
class Forecast:
    fy_label: str
    as_of: pd.Timestamp
    as_of_label: str
    months_elapsed: int
    months_remaining: int
    ytd_sales: float
    ytd_target: float
    ytd_achievement_pct: float
    monthly_run_rate: float
    projected_revenue: float
    full_year_target: float
    projected_achievement_pct: float
    projected_gap: float
    status: str
    required_remaining_sales: float
    required_monthly_run_rate: Optional[float]
    run_rate_improvement_pct: Optional[float]
    channel_table: pd.DataFrame
    region_table: pd.DataFrame
    monthly_table: pd.DataFrame
    actions: list
    scenarios: pd.DataFrame
    scenario_channel: str
    scenario_region: str
    notes: list


def _segment_table(ytd, full, col, months_elapsed, with_full_year) -> pd.DataFrame:
    t = ytd.groupby(col).agg(
        Sales_Lakh=("Current_Sales_Lakh", "sum"),
        Target_Lakh=("Target_Lakh", "sum"),
        Previous_Year_Lakh=("Previous_Year_Sales_Lakh", "sum"),
    ).reset_index()
    t["Achievement_%"] = _pct(t["Sales_Lakh"], t["Target_Lakh"])
    t["Growth_%"] = _pct(t["Sales_Lakh"] - t["Previous_Year_Lakh"], t["Previous_Year_Lakh"])
    t["Gap_Lakh"] = t["Target_Lakh"] - t["Sales_Lakh"]
    t["Contribution_%"] = _pct(t["Sales_Lakh"], pd.Series(t["Sales_Lakh"].sum(), index=t.index))
    t["Status"] = t["Achievement_%"].apply(status_for)
    if with_full_year:
        fy_target = full.groupby(col)["Target_Lakh"].sum()
        t["FY_Target_Lakh"] = t[col].map(fy_target)
        t["Projected_FY_Lakh"] = t["Sales_Lakh"] / months_elapsed * 12
        t["Projected_Gap_Lakh"] = t["FY_Target_Lakh"] - t["Projected_FY_Lakh"]
    return t.sort_values("Gap_Lakh", ascending=False).reset_index(drop=True)


def _scenario_table(ytd, cfg, channel, region, months_elapsed, months_remaining,
                    baseline_forecast, full_year_target) -> pd.DataFrame:
    ch_remaining = ytd.loc[ytd["Channel"] == channel, "Current_Sales_Lakh"].sum() / months_elapsed * months_remaining
    rg_remaining = ytd.loc[ytd["Region"] == region, "Current_Sales_Lakh"].sum() / months_elapsed * months_remaining
    baseline_gap = full_year_target - baseline_forecast
    rows = []
    for name, (ch_up, rg_up) in cfg.cases.items():
        incremental = ch_remaining * ch_up / 100 + rg_remaining * rg_up / 100
        projected = baseline_forecast + incremental
        achievement = _safe_pct(projected, full_year_target)
        rows.append({
            "Scenario": name,
            "Channel_Uplift_%": ch_up,
            "Region_Uplift_%": rg_up,
            "Incremental_Lakh": incremental,
            "Projected_Revenue_Lakh": projected,
            "Achievement_%": achievement,
            "Gap_Lakh": max(full_year_target - projected, 0),
            "Gap_Closed_%": _safe_pct(incremental, baseline_gap) if baseline_gap > 0 else np.nan,
            "Status": status_for(achievement),
        })
    return pd.DataFrame(rows)


def compute_forecast(
    sales: SalesData,
    as_of=None,
    annual_target_override: Optional[float] = None,
    scenario: Optional[ScenarioConfig] = None,
    today: Optional[date] = None,
) -> Forecast:
    df = sales.df
    notes = list(sales.notes)
    months = sales.months
    scenario = scenario or ScenarioConfig()

    # --- as-of month ---
    if as_of is None:
        as_of_ts, note = detect_as_of_month(df, today)
        if note:
            notes.append(note)
    else:
        as_of_ts = _coerce_month(as_of)
    if as_of_ts not in months:
        raise DataValidationError(
            f"{month_label(as_of_ts)} is outside {sales.fy_label} (April to March)."
        )
    months_elapsed = months.index(as_of_ts) + 1
    months_remaining = 12 - months_elapsed
    ytd = df[df["Month_Start"] <= as_of_ts].copy()

    # --- completeness checks ---
    with_sales = set(ytd.loc[ytd["Current_Sales_Lakh"].notna(), "Month_Start"])
    no_sales = [month_label(m) for m in months[:months_elapsed] if m not in with_sales]
    if no_sales:
        notes.append(
            "No sales recorded for " + ", ".join(no_sales)
            + ". These months count as zero, so the forecast may be understated."
        )
    ignored = df[(df["Month_Start"] > as_of_ts) & (df["Current_Sales_Lakh"].fillna(0) > 0)]["Month_Start"].nunique()
    if ignored:
        notes.append(f"Sales for {ignored} month(s) after {month_label(as_of_ts)} are ignored in this view.")

    # --- annual target ---
    full_targets = sales.target_month_count >= 12
    if annual_target_override is not None:
        full_year_target = float(annual_target_override)
        notes.append(f"Annual target of ₹{full_year_target:,.1f} L was entered manually.")
    elif full_targets:
        full_year_target = float(df["Target_Lakh"].sum())
    else:
        raise DataValidationError(
            f"Targets exist for only {sales.target_month_count} of 12 months, so the annual target "
            "cannot be calculated. Add target rows for all 12 months (sales can stay blank for future "
            "months) or enter the annual target manually."
        )
    ytd_target_months = ytd.loc[ytd["Target_Lakh"].notna(), "Month_Start"].nunique()
    if ytd_target_months < months_elapsed:
        notes.append("Target is missing for some completed months, so YTD achievement may be overstated.")

    # --- headline numbers (same method as the original scripts) ---
    ytd_sales = float(ytd["Current_Sales_Lakh"].sum())
    ytd_target = float(ytd["Target_Lakh"].sum())
    run_rate = ytd_sales / months_elapsed
    projected = run_rate * 12
    projected_pct = _safe_pct(projected, full_year_target)
    status = status_for(projected_pct)
    required_remaining = full_year_target - ytd_sales
    required_rr = required_remaining / months_remaining if months_remaining else None
    improvement = (required_rr / run_rate - 1) * 100 if (required_rr is not None and run_rate > 0) else None

    channel_table = _segment_table(ytd, df, "Channel", months_elapsed, full_targets)
    region_table = _segment_table(ytd, df, "Region", months_elapsed, full_targets)

    # --- month-by-month view ---
    by_month = df.groupby("Month_Start").agg(
        Actual_Lakh=("Current_Sales_Lakh", _sum_keep_nan),
        Target_Lakh=("Target_Lakh", _sum_keep_nan),
        Previous_Year_Lakh=("Previous_Year_Sales_Lakh", _sum_keep_nan),
    ).reindex(months)
    done = by_month.index <= as_of_ts
    by_month["Actual_Lakh"] = by_month["Actual_Lakh"].where(done)
    by_month["Forecast_Lakh"] = np.where(done, by_month["Actual_Lakh"], run_rate)
    monthly = by_month.reset_index(names="Month_Start")
    monthly.insert(0, "Month", monthly["Month_Start"].map(month_label))
    monthly = monthly[["Month", "Actual_Lakh", "Forecast_Lakh", "Target_Lakh", "Previous_Year_Lakh"]]

    # --- management priorities ---
    actions = []
    if months_remaining == 0:
        actions.append(f"Financial year complete: final achievement {projected_pct:.1f}% of target.")
    else:
        actions.append({
            STATUS_ON_TRACK: "Maintain current sales velocity",
            STATUS_WATCH: "Accelerate revenue conversion and close the projected gap",
            STATUS_ACTION: "Immediate revenue recovery plan required",
        }.get(status, "Check the input data before drawing conclusions"))
    top_channel, top_region = channel_table.iloc[0], region_table.iloc[0]
    if top_channel["Gap_Lakh"] > 0:
        actions.append(f"Prioritise {top_channel['Channel']} channel with ₹{top_channel['Gap_Lakh']:.1f}L YTD gap")
    if top_region["Gap_Lakh"] > 0:
        actions.append(f"Prioritise {top_region['Region']} region with ₹{top_region['Gap_Lakh']:.1f}L YTD gap")
    if improvement is not None:
        if improvement > 0:
            actions.append(
                f"Increase monthly run rate by approximately {improvement:.1f}% "
                f"(to ₹{required_rr:.1f}L a month) to achieve the annual target"
            )
        else:
            actions.append(
                f"Current run rate already exceeds the ₹{required_rr:.1f}L a month needed for the annual target"
            )

    # --- scenarios ---
    channel = scenario.channel or top_channel["Channel"]
    region = scenario.region or top_region["Region"]
    if channel not in set(df["Channel"]) or region not in set(df["Region"]):
        raise DataValidationError("The scenario channel or region is not in the data.")
    scenarios = _scenario_table(ytd, scenario, channel, region, months_elapsed, months_remaining,
                                projected, full_year_target)

    return Forecast(
        fy_label=sales.fy_label, as_of=as_of_ts, as_of_label=month_label(as_of_ts),
        months_elapsed=months_elapsed, months_remaining=months_remaining,
        ytd_sales=ytd_sales, ytd_target=ytd_target,
        ytd_achievement_pct=_safe_pct(ytd_sales, ytd_target),
        monthly_run_rate=run_rate, projected_revenue=projected,
        full_year_target=full_year_target, projected_achievement_pct=projected_pct,
        projected_gap=full_year_target - projected, status=status,
        required_remaining_sales=required_remaining, required_monthly_run_rate=required_rr,
        run_rate_improvement_pct=improvement, channel_table=channel_table,
        region_table=region_table, monthly_table=monthly, actions=actions,
        scenarios=scenarios, scenario_channel=channel, scenario_region=region, notes=notes,
    )
