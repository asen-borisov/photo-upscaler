@echo off
rem One-time setup when running from source: Python environment + engine + AI models.
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (set PY=python)
if not exist .venv\Scripts\python.exe %PY% -m venv .venv || goto :fail
.venv\Scripts\python -m pip install --upgrade pip >nul
.venv\Scripts\python -m pip install -r requirements.txt || goto :fail
.venv\Scripts\python scripts\setup_engine.py || goto :fail
echo.
echo Setup finished. Double-click "Start Photo Upscaler.bat" to open the app.
pause
exit /b 0
:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
