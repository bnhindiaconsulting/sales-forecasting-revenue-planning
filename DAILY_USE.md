# Daily Use Guide — BNH Sales Forecast

## First time only
1. Install Python 3.10 or newer from python.org (tick "Add Python to PATH" on Windows).
2. Download or clone this repository to your computer.
3. Windows: double-click `run_app.bat`. Mac/Linux: run `./run_app.sh`.
   The first start installs what it needs (about a minute), then opens the app in your browser at http://localhost:8501.

## Every day / every month
1. Double-click `run_app.bat` (or `./run_app.sh`).
2. Upload your latest sales CSV export in the sidebar.
3. Check the **Forecast as of** month. It is picked automatically (the last completed month; a month still running is not counted).
4. Read the status banner, KPIs and management priorities.
5. Click **Download Excel report** to share with management.

Your data stays on your computer. The CSV is read in memory and never saved or uploaded anywhere.

## What your CSV needs
Columns: `Month, Region, Channel, Previous_Year_Sales_Lakh, Current_Sales_Lakh, Target_Lakh`

- Months look like `Apr-26`. The financial year is April to March.
- Include a **target row for all 12 months**. Leave `Current_Sales_Lakh` blank for months that have not happened yet.
- If your export only has some months of target, enter the annual target in the sidebar instead.
- The app tells you in plain words if something is wrong (missing column, text in a number cell, duplicate rows, missing month).
- A template is available from the sidebar button **Download blank CSV template**.

## How the forecast works
- Run rate = YTD sales ÷ months completed
- Projected full year = run rate × 12
- Required run rate = (annual target − YTD sales) ÷ months remaining
- Status: On Track (100% or more of target), Watch (90–100%), Action Required (below 90%)
- Scenarios add an uplift % to the remaining-month run rate of a focus channel and region.
  Change the focus and percentages in the sidebar.

Limit to know: this is a run-rate method, so it does not adjust for seasonality. Treat it as a quick, consistent
read on where you will land, not a precise prediction.

## Without the web app (command line)
    python run_forecast.py my_export.csv
    python run_forecast.py my_export.csv --as-of Oct-26
Saves an Excel report in the `reports` folder.

## Keep real data out of GitHub
This repository is public. `.gitignore` blocks all CSV and Excel files except the demo sample. Keep it that way.

## Files
| File | Purpose |
|---|---|
| `app.py` | The web app |
| `forecast_engine.py` | All calculations and data checks (one place for every rule) |
| `forecast_report.py` | Excel report |
| `run_forecast.py` | Command-line version |
| `test_engine.py` | Automatic tests (`python -m pytest -q`) |
| Older scripts (`forecast_model.py`, etc.) | Left unchanged; the engine reproduces their numbers |
