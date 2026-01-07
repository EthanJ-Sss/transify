@echo off
chcp 65001 >nul
title Unity Prefab Text Extractor
cd /d "%~dp0"

echo Starting Unity Prefab Text Extractor...
echo.

:: Try py launcher first
py --version >nul 2>&1
if %errorlevel%==0 (
    py ExtractPrefabText.py
    goto :end
)

:: Try python
python --version >nul 2>&1
if %errorlevel%==0 (
    python ExtractPrefabText.py
    goto :end
)

:: Try python3
python3 --version >nul 2>&1
if %errorlevel%==0 (
    python3 ExtractPrefabText.py
    goto :end
)

echo.
echo ERROR: Python not found!
echo Please install Python 3.8 or higher
echo Download: https://www.python.org/downloads/
echo.
pause
exit /b 1

:end
if errorlevel 1 (
    echo.
    echo Program error occurred
    echo Make sure dependencies are installed: pip install pandas openpyxl
    echo.
    pause
)
