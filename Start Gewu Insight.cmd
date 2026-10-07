@echo off
setlocal
title Gewu Insight
set "GEWU_INSTALLED=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Gewu Insight\Gewu Insight.lnk"
if not exist "%GEWU_INSTALLED%" (
    echo Gewu Insight is not installed for this Windows account.
    echo Install the local Gewu Insight Setup.exe, then use the Start menu.
    pause
    exit /b 1
)
start "" "%GEWU_INSTALLED%" %*
