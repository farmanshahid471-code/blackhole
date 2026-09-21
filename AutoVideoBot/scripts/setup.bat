@echo off
REM ===========================================================================
REM  AutoVideoBot - one-command setup for Windows 10/11
REM
REM  Double-click this file, or run it from a terminal:
REM      scripts\setup.bat
REM
REM  WHAT IT DOES
REM    1. checks for python and ffmpeg
REM    2. creates a virtual environment in .venv
REM    3. installs the python packages
REM    4. copies .env.example to .env if you do not have one
REM    5. creates the folder structure
REM    6. runs the doctor
REM ===========================================================================
setlocal
cd /d "%~dp0.."
echo ==============================================
echo   AutoVideoBot setup   (%CD%)
echo ==============================================

REM ---------------------------------------------------------------- 1. python
where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python was not found.
    echo   Install it from https://www.python.org/downloads/
    echo   IMPORTANT: tick "Add python.exe to PATH" during installation.
    pause
    exit /b 1
)
python --version
echo   python detected.

REM ---------------------------------------------------------------- 2. ffmpeg
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo.
    echo   ffmpeg NOT found. This is the most common Windows problem. Fix it:
    echo     1. download https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
    echo     2. unzip it to   C:\ffmpeg
    echo     3. press Windows key, type "environment variables", open
    echo        "Edit the system environment variables"
    echo     4. Environment Variables... -^> under "System variables" find Path -^> Edit
    echo     5. New -^>  C:\ffmpeg\bin  -^> OK, OK
    echo     6. CLOSE this window and run setup.bat again
    echo.
    echo   Continuing anyway so the rest of the setup finishes...
) else (
    echo   ffmpeg detected.
)

REM ------------------------------------------------------- 3. venv + packages
if not exist .venv (
    echo   creating virtual environment .venv ...
    python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
echo   installing python packages (1-3 minutes) ...
python -m pip install --quiet -r requirements.txt

REM --------------------------------------------------------------- 4. secrets
if not exist .env (
    copy /y .env.example .env >nul
    echo   created .env from .env.example  -^>  EDIT IT with Notepad and add your keys
) else (
    echo   .env already exists - leaving it alone
)

REM -------------------------------------------------------------- 5. folders
if not exist assets\background_music mkdir assets\background_music
if not exist assets\fonts mkdir assets\fonts
if not exist workspace\projects mkdir workspace\projects
if not exist workspace\tmp mkdir workspace\tmp
echo   folder structure ready

REM ----------------------------------------------------------------- 6. check
echo.
echo   running the system doctor ...
python main.py doctor

echo.
echo ==============================================
echo   SETUP COMPLETE. Two commands to remember:
echo.
echo     .venv\Scripts\activate
echo     python main.py run "my first video" --topic "why the sky is blue" --duration 60
echo.
echo   Or with YOUR OWN script:
echo     python main.py run "my video" --script examples\black_holes_script.txt
echo ==============================================
pause
