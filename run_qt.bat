@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py qt_app.py
) else (
    python qt_app.py
)
if errorlevel 1 pause
