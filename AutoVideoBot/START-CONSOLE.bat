@echo off
REM ===========================================================================
REM  AutoVideoBot - COMMAND LINE (Windows)
REM ===========================================================================
REM  Double-click to open a ready-to-use terminal inside the project, with the
REM  bot's private Python already activated. Everything below works instantly.
REM
REM  Use this if you prefer typing commands, or if the web interface cannot
REM  start for some reason.
REM ===========================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"
title AutoVideoBot - command line

set "VENV=.venv"
set "VPY=%VENV%\Scripts\python.exe"

cls
echo.
echo  ==========================================================================
echo    AutoVideoBot  -  command line
echo  ==========================================================================
echo.

if not exist "%VPY%" (
  echo    The bot is not installed yet.
  echo.
  if exist "INSTALL-WINDOWS.bat" (
    echo    Setting it up now ...
    call "INSTALL-WINDOWS.bat"
    exit /b %errorlevel%
  )
  echo  [X] .venv is missing. Run INSTALL-WINDOWS.bat first.
  pause
  exit /b 1
)

REM activate the environment for this window
call "%VENV%\Scripts\activate.bat"

echo    Ready. Popular commands:
echo.
echo      main.py doctor                                       check everything
echo      main.py test                                         tiny 8-second video
echo      main.py run "my video" --topic "black holes" --duration 120
echo      main.py run "my video" --script examples\black_holes_script.txt
echo      main.py web                                          the point-and-click UI
echo      main.py providers                                    tools you can swap
echo      main.py inspect "my video"                           what got built
echo.
echo    Your videos appear in:  workspace\projects\^<name^>\output\final.mp4
echo.
echo    Type  main.py --help  for the full list.
echo.
echo  ==========================================================================
echo.

cmd /k
endlocal
exit /b 0
