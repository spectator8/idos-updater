@echo off
title IDOS Aktualizator (Web)
cd /d "%~dp0"
python main.py --web
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Doslo k chybe pri spusteni. Zkontrolujte, zda mate nainstalovany Python.
    pause
)
