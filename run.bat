@echo off
echo ========================================
echo Voice Shock Control - Development Run
echo ========================================
echo.

echo Checking dependencies...
pip show customtkinter >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install -r requirements.txt
)

echo.
echo Starting application...
echo.

python voice_shock_control.py

if errorlevel 1 (
    echo.
    echo ========================================
    echo Application exited with an error.
    echo ========================================
    pause
)
