@echo off
REM ---------------------------------------------------------------------------
REM Publish this working copy to https://github.com/fanjx000/FTP-One-Way-mirror
REM
REM Prerequisite: the EMPTY repository must already exist on GitHub
REM (New repository -> name FTP-One-Way-mirror -> do NOT add README/licence).
REM
REM Run this file by double-clicking it, or from a terminal:  publish.bat
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

set REPO=https://github.com/fanjx000/FTP-One-Way-mirror.git

where git >nul 2>nul || goto :nogit

echo [1/3] checking the local repository ...
git rev-parse --git-dir >nul 2>nul || goto :norepo
git status --porcelain | findstr /r "." >nul && echo       (note: uncommitted changes are NOT pushed)

echo [2/3] setting the remote "origin" ...
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    git remote add origin %REPO% || goto :err
    echo       added origin -^> %REPO%
) else (
    git remote set-url origin %REPO% || goto :err
    echo       origin already present, URL refreshed
)

echo [3/3] pushing branch "main" ...
echo.
echo   If git asks for credentials, use a personal access token as the
echo   password (GitHub -> Settings -> Developer settings -> Personal access
echo   tokens -> Fine-grained -> Contents: Read and write).
echo.
git push -u origin main || goto :pusherr

echo.
echo Done.  https://github.com/fanjx000/FTP-One-Way-mirror
echo Next: Releases -^> Draft a new release -^> tag v1.8.2 -^> attach dist\FtpSync.exe
pause
exit /b 0

:nogit
echo.
echo git was not found in PATH. Install Git for Windows: https://git-scm.com/download/win
pause
exit /b 1

:norepo
echo.
echo This folder is not a git repository. Run "git init -b main" first.
pause
exit /b 1

:pusherr
echo.
echo PUSH FAILED.
echo  * 404 / "repository not found"  -> create the empty repo on GitHub first,
echo    and make sure the name is exactly FTP-One-Way-mirror
echo  * 403 / "permission denied"     -> the token lacks Contents:write
echo  * "Authentication failed"       -> use a personal access token as password
pause
exit /b 1

:err
echo.
echo FAILED while configuring the remote.
pause
exit /b 1
