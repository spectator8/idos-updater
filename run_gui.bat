@echo off
title IDOS Aktualizator (GUI)
cd /d "%~dp0"
python main.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Doslo k chybe pri spusteni. Skontrolujte, ci mate nainstalovany Python.
    pause
)
