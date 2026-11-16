"""
Command-line runner: CSV in, forecast printed, Excel report saved.

    python run_forecast.py my_sales_export.csv
    python run_forecast.py my_sales_export.csv --as-of Oct-26
    python run_forecast.py my_sales_export.csv --annual-target 977.04

Reports are saved in the 'reports' folder (which is excluded from git).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forecast_engine import DataValidationError, compute_forecast, load_sales_data
from forecast_report import build_excel_report


def main() -> int:
    parser = argparse.ArgumentParser(description="BNH sales forecast from a CSV export")
    parser.add_argument("csv", nargs="?", default="sales_forecasting_sample_data.csv")
    parser.add_argument("--as-of", help="Last completed month, e.g. Oct-26 (default: detected)")
    parser.add_argument("--annual-target", type=float, help="Annual target in ₹ Lakh, if the file lacks 12 months of targets")
    parser.add_argument("--out", help="Excel report path (default: reports/BNH_Sales_Forecast_<month>.xlsx)")
    args = parser.parse_args()

    try:
        sales = load_sales_data(args.csv)
        f = compute_forecast(sales, as_of=args.as_of, annual_target_override=args.annual_target)
    except (DataValidationError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"\n{f.fy_label} | as of {f.as_of_label} | status: {f.status.upper()}")
    print(f"YTD sales            ₹{f.ytd_sales:,.2f} L  ({f.ytd_achievement_pct:.1f}% of YTD target)")
    print(f"Monthly run rate     ₹{f.monthly_run_rate:,.2f} L")
    print(f"Projected full year  ₹{f.projected_revenue:,.2f} L  ({f.projected_achievement_pct:.1f}% of ₹{f.full_year_target:,.2f} L target)")
    print(f"Projected gap        ₹{f.projected_gap:,.2f} L")
    if f.required_monthly_run_rate is not None:
        print(f"Required run rate    ₹{f.required_monthly_run_rate:,.2f} L a month for the remaining {f.months_remaining} months")
    print("\nPriorities:")
    for i, action in enumerate(f.actions, 1):
        print(f"  {i}. {action}")
    if f.notes:
        print("\nData notes:")
        for note in f.notes:
            print(f"  - {note}")

    out = Path(args.out) if args.out else Path("reports") / f"BNH_Sales_Forecast_{f.as_of_label}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(build_excel_report(f))
    print(f"\nExcel report saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
