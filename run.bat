@echo off
setlocal
cd /d "%~dp0"

rem Launch through the windowed interpreter so no blank console stays open
rem behind the Qt window for the whole session.
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw qt_app.py
    goto :eof
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw qt_app.py
    goto :eof
)

where py >nul 2>nul
if %errorlevel%==0 (
    py qt_app.py
) else (
    python qt_app.py
)
if errorlevel 1 pause
