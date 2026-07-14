@echo off
cd /d "%~dp0"
py app.py
if errorlevel 1 pause
