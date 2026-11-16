@echo off
REM One-step launcher for Windows: sets itself up the first time, then opens the app in your browser.
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
  echo First run: installing ^(about a minute^)...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  pip install -r requirements.txt
  if errorlevel 1 (
    echo Install failed. Check that Python is installed and you are online.
    pause
    exit /b 1
  )
) else (
  call .venv\Scripts\activate.bat
)
start "" /b cmd /c "timeout /t 5 /nobreak >nul && start http://localhost:8501"
streamlit run app.py --server.headless true
pause
