@echo off===========================================

title MediTrack - Emergency Medical Record System
color 0A

echo.
echo  ===================================================
echo    MediTrack - Emergency Medical Record System
echo  ===================================================
echo.
echo  Checking Python installation...

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Python is not installed!
    echo  Please download Python from: https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo  Python found!
echo.
echo  Installing required packages (this may take a minute on first run)...
pip install -r requirements.txt --quiet

if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Could not install packages.
    echo  Try running: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

echo  All packages installed!
echo.
echo  Starting MediTrack...
echo  Open your browser at: http://localhost:5000
echo.
echo  Press CTRL+C to stop the server.
echo.

python run.py

pause
