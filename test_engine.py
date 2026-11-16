"""Tests for the forecast engine. Run with:  python -m pytest -q"""

import io
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from forecast_engine import (
    DataValidationError,
    ScenarioConfig,
    compute_forecast,
    detect_as_of_month,
    load_sales_data,
)

SAMPLE = Path(__file__).parent / "sales_forecasting_sample_data.csv"


def raw_sample() -> pd.DataFrame:
    return pd.read_csv(SAMPLE, dtype=str)


def load(df: pd.DataFrame):
    buffer = io.BytesIO(df.to_csv(index=False).encode("utf-8"))
    return load_sales_data(buffer)


# ---- results must match the original scripts (Sep-26 view of the sample data) ----

def test_headline_numbers_match_original_scripts():
    f = compute_forecast(load_sales_data(SAMPLE), as_of="Sep-26")
    assert f.months_elapsed == 6 and f.months_remaining == 6
    assert f.ytd_sales == pytest.approx(458.18, abs=0.01)
    assert f.ytd_target == pytest.approx(488.52, abs=0.01)
    assert f.monthly_run_rate == pytest.approx(76.36, abs=0.01)
    assert f.projected_revenue == pytest.approx(916.36, abs=0.01)
    assert f.full_year_target == pytest.approx(977.04, abs=0.01)
    assert f.projected_achievement_pct == pytest.approx(93.8, abs=0.05)
    assert f.projected_gap == pytest.approx(60.68, abs=0.01)
    assert f.required_monthly_run_rate == pytest.approx(86.48, abs=0.01)
    assert f.run_rate_improvement_pct == pytest.approx(13.2, abs=0.05)
    assert f.status == "Watch"


def test_scenarios_match_original_simulator():
    f = compute_forecast(load_sales_data(SAMPLE), as_of="Sep-26", scenario=ScenarioConfig("GT", "West"))
    by_name = f.scenarios.set_index("Scenario")
    assert by_name.loc["UPSIDE", "Incremental_Lakh"] == pytest.approx(36.52, abs=0.01)
    assert by_name.loc["UPSIDE", "Achievement_%"] == pytest.approx(97.5, abs=0.05)
    assert by_name.loc["STRETCH", "Projected_Revenue_Lakh"] == pytest.approx(971.14, abs=0.01)
    assert by_name.loc["STRETCH", "Gap_Lakh"] == pytest.approx(5.90, abs=0.01)
    assert by_name.loc["STRETCH", "Gap_Closed_%"] == pytest.approx(90.3, abs=0.05)


def test_default_focus_is_largest_gap_channel_and_region():
    f = compute_forecast(load_sales_data(SAMPLE), as_of="Sep-26")
    assert (f.scenario_channel, f.scenario_region) == ("GT", "West")


# ---- choosing the as-of month automatically ----

def blank_after(df: pd.DataFrame, months: list) -> pd.DataFrame:
    df = df.copy()
    df.loc[df["Month"].isin(months), "Current_Sales_Lakh"] = ""
    return df


def test_future_months_left_blank_are_fine():
    sales = load(blank_after(raw_sample(), ["Nov-26", "Dec-26", "Jan-27", "Feb-27", "Mar-27"]))
    f = compute_forecast(sales, today=date(2026, 11, 16))
    assert f.as_of_label == "Oct-26" and f.months_elapsed == 7
    assert f.notes == []


def test_month_still_running_is_not_treated_as_complete():
    sales = load(blank_after(raw_sample(), ["Dec-26", "Jan-27", "Feb-27", "Mar-27"]))
    month, note = detect_as_of_month(sales.df, today=date(2026, 11, 16))
    assert month.strftime("%b-%y") == "Oct-26" and "still running" in note
    month, note = detect_as_of_month(sales.df, today=date(2026, 11, 30))
    assert month.strftime("%b-%y") == "Nov-26" and note is None


def test_year_complete_has_no_required_run_rate():
    f = compute_forecast(load_sales_data(SAMPLE), as_of="Mar-27")
    assert f.months_remaining == 0 and f.required_monthly_run_rate is None
    assert "Financial year complete" in f.actions[0]


def test_no_sales_at_all_is_an_error():
    with pytest.raises(DataValidationError, match="No sales"):
        compute_forecast(load(blank_after(raw_sample(), list(raw_sample()["Month"].unique()))))


# ---- bad input is caught with a clear message, never a silent wrong answer ----

def test_missing_column():
    with pytest.raises(DataValidationError, match="Target_Lakh"):
        load(raw_sample().drop(columns=["Target_Lakh"]))


def test_non_numeric_value_names_the_row():
    df = raw_sample()
    df.loc[3, "Current_Sales_Lakh"] = "abc"
    with pytest.raises(DataValidationError, match=r"Current_Sales_Lakh.*row\(s\) 5"):
        load(df)


def test_unreadable_month():
    df = raw_sample()
    df.loc[0, "Month"] = "April twenty six"
    with pytest.raises(DataValidationError, match="Month column"):
        load(df)


def test_targets_for_fewer_than_12_months_need_manual_annual_target():
    sales = load(raw_sample()[~raw_sample()["Month"].isin(["Jan-27", "Feb-27", "Mar-27"])])
    with pytest.raises(DataValidationError, match="only 9 of 12"):
        compute_forecast(sales, as_of="Sep-26")
    f = compute_forecast(sales, as_of="Sep-26", annual_target_override=977.04)
    assert f.full_year_target == pytest.approx(977.04) and f.projected_gap == pytest.approx(60.68, abs=0.01)


def test_duplicate_rows_are_added_with_a_warning():
    df = raw_sample()
    sales = load(pd.concat([df, df.iloc[[0]]]))
    assert any("share the same Month" in n for n in sales.notes)
    first = sales.df.iloc[0]
    assert first["Current_Sales_Lakh"] == pytest.approx(2 * float(df.loc[0, "Current_Sales_Lakh"]))


def test_missing_sales_month_is_flagged():
    df = raw_sample()
    df.loc[df["Month"] == "Jun-26", "Current_Sales_Lakh"] = ""
    f = compute_forecast(load(df), as_of="Sep-26")
    assert any("No sales recorded for Jun-26" in n for n in f.notes)


# ---- tolerant of how real exports look ----

def test_header_case_spaces_rupee_signs_and_commas():
    df = raw_sample().rename(columns={"Current_Sales_Lakh": "current sales lakh", "Region": " region "})
    df["current sales lakh"] = "₹" + df["current sales lakh"].map(lambda v: f"{float(v):,.2f}")
    f = compute_forecast(load(df), as_of="Sep-26")
    assert f.ytd_sales == pytest.approx(458.18, abs=0.02)


def test_channel_spelling_differences_are_merged():
    df = raw_sample()
    df.loc[df["Channel"] == "GT", "Channel"] = ["GT", "gt", "Gt"] * (len(df[df["Channel"] == "GT"]) // 3)
    sales = load(df)
    assert sorted(sales.channels) == ["GT", "MT", "Retail"]


def test_only_latest_financial_year_is_used():
    old = raw_sample()
    old["Month"] = old["Month"].str.replace("-26", "-25").str.replace("-27", "-26")
    sales = load(pd.concat([old, raw_sample()]))
    assert sales.fy_label == "FY 2026-27" and any("more than one financial year" in n for n in sales.notes)
    assert compute_forecast(sales, as_of="Sep-26").ytd_sales == pytest.approx(458.18, abs=0.01)
