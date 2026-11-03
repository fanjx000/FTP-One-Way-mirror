@echo off
REM Build the portable Windows application as ONE self-contained file: dist\FtpSync.exe
setlocal
cd /d "%~dp0"

echo [1/3] installing build dependencies (PySide6, PyInstaller) if needed ...
python -m pip install --quiet --upgrade PySide6-Essentials pyinstaller || goto :err

echo [2/3] generating icon ...
python tools\make_icon.py || goto :err

echo [3/3] packaging ...
if exist build_one rd /s /q build_one
if exist dist_new rd /s /q dist_new
python -m PyInstaller --noconfirm FtpSync-onefile.spec --workpath build_one --distpath dist_new || goto :err

REM the single exe replaces both the old folder build and any stale file
if exist dist\FtpSync rd /s /q dist\FtpSync
if exist dist\FtpSync.exe del /f /q dist\FtpSync.exe
move dist_new\FtpSync.exe dist\FtpSync.exe >nul
RD /S /Q dist_new 2>nul

echo.
echo Done.  Single-file build:  %~dp0dist\FtpSync.exe
echo Copy that one file anywhere on Windows 11 and run it - no installation, no _internal folder.
pause
exit /b 0

:err
echo.
echo BUILD FAILED (see messages above).
pause
exit /b 1
