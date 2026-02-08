@echo off
echo ========================================
echo Voice Shock Control - Build Script
echo ========================================
echo.

echo Checking for PyInstaller...
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
) else (
    echo PyInstaller is installed.
)

echo.
echo Building executable...
echo This may take several minutes...
echo.

pyinstaller voice_shock_control.spec

if errorlevel 1 (
    echo.
    echo ========================================
    echo BUILD FAILED!
    echo Check the error messages above.
    echo ========================================
    pause
    exit /b 1
) else (
    echo.
    echo ========================================
    echo BUILD SUCCESSFUL!
    echo.
    echo Executable location:
    echo dist\VoiceShockControl.exe
    echo ========================================
    echo.
    echo Press any key to open the dist folder...
    pause >nul
    explorer dist
)
