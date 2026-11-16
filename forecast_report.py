"""Excel report and display helpers for the forecast. Pure presentation: no business rules live here."""

from __future__ import annotations

import io

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill

from forecast_engine import Forecast

_HEADER_FILL = PatternFill("solid", fgColor="1F3864")


def pretty_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Sales_Lakh -> 'Sales (₹L)', Achievement_% -> 'Achievement %'."""
    out = df.copy()
    out.columns = [
        c.replace("_Lakh", " (₹L)").replace("_%", " %").replace("_", " ") for c in out.columns
    ]
    return out


def summary_frame(f: Forecast) -> pd.DataFrame:
    rows = [
        ("Financial year", f.fy_label),
        ("As of (last completed month)", f.as_of_label),
        ("Months completed", f.months_elapsed),
        ("Months remaining", f.months_remaining),
        ("Status", f.status),
        ("YTD sales (₹L)", f.ytd_sales),
        ("YTD target (₹L)", f.ytd_target),
        ("YTD achievement %", f.ytd_achievement_pct),
        ("Current monthly run rate (₹L)", f.monthly_run_rate),
        ("Projected full-year revenue (₹L)", f.projected_revenue),
        ("Annual target (₹L)", f.full_year_target),
        ("Projected achievement %", f.projected_achievement_pct),
        ("Projected gap (₹L)", f.projected_gap),
        ("Required monthly run rate for remaining months (₹L)", f.required_monthly_run_rate),
        ("Run-rate increase needed %", f.run_rate_improvement_pct),
    ]
    out = pd.DataFrame(rows, columns=["Metric", "Value"])
    out["Value"] = out["Value"].map(lambda v: round(v, 2) if isinstance(v, float) else v)
    return out


def _style_sheet(ws) -> None:
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"
    for column in ws.columns:
        longest = max(len(str(c.value)) if c.value is not None else 0 for c in column)
        ws.column_dimensions[column[0].column_letter].width = min(max(longest + 2, 10), 70)
        for cell in column[1:]:
            if isinstance(cell.value, float):
                cell.number_format = "#,##0.0"


def build_excel_report(f: Forecast) -> bytes:
    """One workbook a manager can open: summary, priorities, channel, region, months, scenarios, data notes."""
    priorities = pd.DataFrame({"Priority": range(1, len(f.actions) + 1), "Action": f.actions})
    notes = pd.DataFrame({"Data notes": f.notes or ["No issues found in the input data."]})
    scenarios = pretty_columns(f.scenarios.round(2))
    sheets = {
        "Summary": summary_frame(f),
        "Priorities": priorities,
        "Channel": pretty_columns(f.channel_table.round(2)),
        "Region": pretty_columns(f.region_table.round(2)),
        f"Scenarios ({f.scenario_channel}-{f.scenario_region})": scenarios,
        "Month by month": pretty_columns(f.monthly_table.round(2)),
        "Data notes": notes,
    }
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)
        for ws in writer.book.worksheets:
            _style_sheet(ws)
    return buffer.getvalue()
