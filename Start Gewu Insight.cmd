@echo off
setlocal
cd /d "%~dp0"
title Gewu Insight - Desktop from Source
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".venv\Scripts\python.exe" (
    echo First-time setup is required. Run these commands in this folder:
    echo   py -3 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo Then double-click this launcher again.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -B "scripts\windows_source.py" %*
if errorlevel 1 (
    echo.
    echo Startup failed. See the message above.
    pause
    exit /b 1
)
