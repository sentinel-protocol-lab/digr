@echo off
:: Sample Library Manager - Batch Launcher
:: Double-click this file to install. No PowerShell policy changes needed.

echo.
echo   Sample Library Manager - Installer
echo   =====================================
echo.

:: Run the PowerShell installer with execution policy bypass
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   Installation failed. See error above.
    pause
    exit /b 1
)
