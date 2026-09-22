@echo off
REM ===========================================================================
REM  AutoVideoBot - START THE WEB INTERFACE (Windows)
REM ===========================================================================
REM  Double-click this any time you want to use the bot.
REM
REM  It opens the point-and-click interface in your browser: create videos,
REM  watch the live build log, play and download the results, change settings
REM  and paste API keys - no terminal commands needed.
REM
REM  If something is missing, this file fixes it instead of failing:
REM    * no Python environment yet  -> runs the full installer for you
REM    * web packages missing       -> downloads them
REM    * .env missing               -> creates it from the example
REM ===========================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AutoVideoBot - web interface

set "VENV=.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "PORT=8765"

echo.
echo  ==========================================================================
echo    AutoVideoBot  -  web interface
echo  ==========================================================================
echo.

REM --- 1. is the environment there? if not, install it -----------------------
if not exist "%VPY%" (
  echo    First run detected - the bot needs to set itself up.
  echo.
  if exist "INSTALL-WINDOWS.bat" (
    call "INSTALL-WINDOWS.bat"
    exit /b %errorlevel%
  ) else (
    echo  [X] .venv is missing and INSTALL-WINDOWS.bat was not found.
    echo      Re-download the project, or create the environment with:
    echo         python -m venv .venv
    echo         .venv\Scripts\python -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
  )
)

REM --- 2. are the web packages installed? -----------------------------------
"%VPY%" -c "import fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
  echo    Downloading the web interface packages ^(one time, about 20 MB^) ...
  "%VPY%" -m pip install --disable-pip-version-check --quiet fastapi "uvicorn[standard]" python-multipart psutil
  if errorlevel 1 (
    echo.
    echo  [X] Could not download them. Check your internet connection and try
    echo      again, or run INSTALL-WINDOWS.bat to repair the installation.
    echo.
    pause
    exit /b 1
  )
  echo    done.
)

REM --- 3. make sure the folders and .env exist -------------------------------
if not exist "workspace" mkdir "workspace"
if not exist "workspace\projects" mkdir "workspace\projects"
if not exist ".env" if exist ".env.example" copy /y ".env.example" ".env" >nul

REM --- 4. free the port if an old copy is still running -----------------------
netstat -ano 2>nul | findstr /r ":%PORT% .*LISTENING" >nul 2>&1
if !errorlevel!==0 (
  echo    Closing an earlier copy of the interface that is still running ...
  for /f "tokens=5" %%P in ('netstat -ano ^| findstr /r ":%PORT% .*LISTENING"') do (
    taskkill /pid %%P /f >nul 2>&1
  )
  timeout /t 1 /nobreak >nul
)

REM --- 5. go -----------------------------------------------------------------
echo    Starting the bot on http://127.0.0.1:%PORT%
echo.
echo    Your browser will open by itself in a few seconds.
echo.
echo    ---------------------------------------------------------------
echo     KEEP THIS WINDOW OPEN while you use the bot.
echo     Closing it (or pressing Ctrl+C) stops the bot.
echo    ---------------------------------------------------------------
echo.

REM the server opens the browser itself; if a firewall asks, allow it
"%VPY%" main.py web --port %PORT%

echo.
echo    The bot has stopped.
echo.
pause
endlocal
exit /b 0
