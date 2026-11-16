"""
BNH Sales Forecast - daily-use web app.

Run:  streamlit run app.py     (or double-click run_app.bat / run_app.sh)
Your data stays on this computer: the CSV is read in memory and never saved or sent anywhere.
"""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import altair as alt
import streamlit as st

from forecast_engine import (
    DataValidationError,
    ScenarioConfig,
    SalesData,
    compute_forecast,
    detect_as_of_month,
    load_sales_data,
    month_label,
)
from forecast_report import build_excel_report, pretty_columns

APP_DIR = Path(__file__).parent
SAMPLE_FILE = APP_DIR / "sales_forecasting_sample_data.csv"
TEMPLATE_CSV = (
    "Month,Region,Channel,Previous_Year_Sales_Lakh,Current_Sales_Lakh,Target_Lakh\n"
    "Apr-26,North,GT,10.0,10.8,11.8\n"
    "Apr-26,North,MT,7.0,7.56,8.26\n"
    "Apr-26,West,GT,11.0,11.88,12.98\n"
)

st.set_page_config(page_title="BNH Sales Forecast", page_icon="📈", layout="wide")


@st.cache_data(show_spinner=False)
def _load(data: bytes) -> SalesData:
    return load_sales_data(io.BytesIO(data))


def lakh(value) -> str:
    return "—" if value is None else f"₹{value:,.1f} L"


def show_table(frame) -> None:
    frame = pretty_columns(frame.round(1))
    try:
        st.dataframe(frame, hide_index=True, width="stretch")
    except TypeError:  # older Streamlit versions
        st.dataframe(frame, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------- sidebar: data
st.sidebar.title("BNH Sales Forecast")
st.sidebar.subheader("1. Load data")
upload = st.sidebar.file_uploader("Monthly sales CSV export", type=["csv"])
use_sample = st.sidebar.checkbox("Use sample data (demo)")
st.sidebar.download_button("Download blank CSV template", TEMPLATE_CSV, "sales_template.csv", "text/csv")

if upload is not None:
    data_bytes, source_name = upload.getvalue(), upload.name
elif use_sample:
    data_bytes, source_name = SAMPLE_FILE.read_bytes(), "sample data (demo)"
else:
    st.title("Sales Forecast & Revenue Planning")
    st.info("Upload your monthly sales CSV in the sidebar to begin, or tick **Use sample data** to see a demo.")
    st.markdown(
        "**Expected columns:** `Month`, `Region`, `Channel`, `Previous_Year_Sales_Lakh`, "
        "`Current_Sales_Lakh`, `Target_Lakh`. Months look like `Apr-26`. "
        "Include a target row for all 12 months of the financial year (April to March); "
        "leave sales blank for months that have not happened yet."
    )
    st.stop()

try:
    sales = _load(data_bytes)
except DataValidationError as exc:
    st.error(f"**This file cannot be used yet.** {exc}")
    st.stop()

# ---------------------------------------------------------------- sidebar: period
st.sidebar.subheader("2. Forecast period")
options = sales.months_with_sales
if not options:
    st.error("No sales were found in Current_Sales_Lakh.")
    st.stop()
auto_month, auto_note = detect_as_of_month(sales.df, date.today())
labels = [month_label(m) for m in options]
if upload is None:  # demo data: open on Sep-26, the view the original scripts used
    default_label = "Sep-26" if "Sep-26" in labels else labels[-1]
else:
    default_label = month_label(auto_month) if auto_month in options else labels[-1]
chosen = st.sidebar.selectbox(
    "Forecast as of (last completed month)", labels, index=labels.index(default_label)
)
as_of_ts = options[labels.index(chosen)]
if auto_note and upload is not None:
    st.sidebar.info(auto_note)

override = None
if sales.target_month_count < 12:
    st.sidebar.warning(f"Targets found for only {sales.target_month_count} of 12 months.")
    entered = st.sidebar.number_input("Annual target (₹ Lakh)", min_value=0.0, value=0.0, step=10.0)
    if entered <= 0:
        st.info("Enter the annual target in the sidebar, or add target rows for all 12 months to your file.")
        st.stop()
    override = entered

# ---------------------------------------------------------------- sidebar: scenarios
st.sidebar.subheader("3. Scenario assumptions")
try:
    base = compute_forecast(sales, as_of=as_of_ts, annual_target_override=override)
except DataValidationError as exc:
    st.error(str(exc))
    st.stop()
channel = st.sidebar.selectbox("Focus channel", sales.channels, index=sales.channels.index(base.scenario_channel))
region = st.sidebar.selectbox("Focus region", sales.regions, index=sales.regions.index(base.scenario_region))
upside = st.sidebar.slider("Upside case: sales uplift on remaining months (%)", 0, 50, 10)
stretch = st.sidebar.slider("Stretch case: sales uplift on remaining months (%)", 0, 50, 15)
config = ScenarioConfig(
    channel=channel,
    region=region,
    cases={"BASE": (0.0, 0.0), "UPSIDE": (float(upside), float(upside)), "STRETCH": (float(stretch), float(stretch))},
)
f = compute_forecast(sales, as_of=as_of_ts, annual_target_override=override, scenario=config)

st.sidebar.subheader("4. Export")
st.sidebar.download_button(
    "Download Excel report",
    build_excel_report(f),
    file_name=f"BNH_Sales_Forecast_{f.as_of_label}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# ---------------------------------------------------------------- main page
st.title("Sales Forecast & Revenue Planning")
st.caption(f"{f.fy_label}  ·  as of {f.as_of_label}  ·  {source_name}")

headline = (
    f"**{f.status.upper()}** — projected full-year revenue {lakh(f.projected_revenue)} is "
    f"{f.projected_achievement_pct:.1f}% of the {lakh(f.full_year_target)} target."
)
{"On Track": st.success, "Watch": st.warning, "Action Required": st.error}.get(f.status, st.info)(headline)

row1 = st.columns(4)
row1[0].metric("YTD sales", lakh(f.ytd_sales))
row1[1].metric("YTD achievement", f"{f.ytd_achievement_pct:.1f}%", help="YTD sales vs the target for the months completed")
row1[2].metric("Projected full year", lakh(f.projected_revenue), help="Monthly run rate × 12")
row1[3].metric("Projected achievement", f"{f.projected_achievement_pct:.1f}%")

row2 = st.columns(4)
row2[0].metric("Annual target", lakh(f.full_year_target))
row2[1].metric("Projected gap" if f.projected_gap > 0 else "Projected surplus", lakh(abs(f.projected_gap)))
row2[2].metric("Run rate per month", lakh(f.monthly_run_rate), help="YTD sales ÷ months completed")
if f.required_monthly_run_rate is not None:
    row2[3].metric(
        "Required run rate per month",
        lakh(f.required_monthly_run_rate),
        delta=f"{f.required_monthly_run_rate - f.monthly_run_rate:+.1f} L vs current",
        delta_color="inverse",
        help="What the remaining months must average to hit the annual target",
    )
else:
    row2[3].metric("Required run rate per month", "—")

st.subheader("Management priorities")
for number, action in enumerate(f.actions, 1):
    st.markdown(f"{number}. {action}")

st.subheader("Monthly sales vs target")
long = (
    f.monthly_table.rename(columns={
        "Actual_Lakh": "Actual", "Forecast_Lakh": "Forecast (run rate)",
        "Target_Lakh": "Target", "Previous_Year_Lakh": "Previous year",
    })
    .melt("Month", var_name="Series", value_name="₹ Lakh")
    .dropna()
)
chart = (
    alt.Chart(long)
    .mark_line(point=True)
    .encode(
        x=alt.X("Month:N", sort=list(f.monthly_table["Month"]), title=None),
        y=alt.Y("₹ Lakh:Q", scale=alt.Scale(zero=False)),
        color=alt.Color("Series:N", title=None),
        tooltip=["Month", "Series", alt.Tooltip("₹ Lakh:Q", format=",.1f")],
    )
    .properties(height=320)
)
try:
    st.altair_chart(chart, width="stretch")
except TypeError:
    st.altair_chart(chart, use_container_width=True)

tab_channel, tab_region, tab_scen, tab_month, tab_data = st.tabs(
    ["By channel", "By region", "Scenarios", "Month by month", "Data checks"]
)
with tab_channel:
    show_table(f.channel_table)
with tab_region:
    show_table(f.region_table)
with tab_scen:
    st.caption(
        f"Uplift is applied to the remaining-month run rate of the {f.scenario_channel} channel and the "
        f"{f.scenario_region} region. Where they overlap, both uplifts apply. "
        "Change the focus and percentages in the sidebar."
    )
    show_table(f.scenarios)
with tab_month:
    show_table(f.monthly_table)
with tab_data:
    if f.notes:
        for note in f.notes:
            st.warning(note)
    else:
        st.success("No issues found in the input data.")
    st.caption(
        f"{len(sales.df)} rows loaded · {len(sales.months_with_sales)} month(s) with sales · "
        f"{sales.target_month_count} month(s) with targets."
    )
