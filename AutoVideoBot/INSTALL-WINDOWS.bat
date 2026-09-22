@echo off
REM ===========================================================================
REM  AutoVideoBot - WINDOWS ONE-CLICK INSTALLER
REM ===========================================================================
REM  Just double-click this file. It will:
REM
REM    1. find Python (and download it from python.org if you do not have it)
REM    2. create a private Python environment inside this folder
REM    3. download every library the bot needs  (pip)
REM    4. download a private copy of FFmpeg     (the video engine)
REM    5. create your .env file for API keys
REM    6. check everything with the built-in doctor
REM    7. open the web interface and the 5-minute guide
REM
REM  Nothing is installed system-wide, nothing is added to your PATH, and
REM  nothing is shared with other programs. Everything lives in this folder,
REM  so you can delete the folder to uninstall completely.
REM
REM  The script is safe to run again at any time: it skips what is done and
REM  repairs what is broken. That is also the fix for most problems.
REM ===========================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

title AutoVideoBot installer

echo.
echo  ==========================================================================
echo    AutoVideoBot  -  installation
echo  ==========================================================================
echo.
echo    This will take 3 to 10 minutes the first time, depending on your
echo    internet speed. You may keep this window open and watch.
echo.
echo    Folder: %CD%
echo.

REM ---------------------------------------------------------------------------
REM  0. sanity: are we in the right folder?
REM ---------------------------------------------------------------------------
if not exist "main.py" (
  echo  [X] main.py was not found next to this installer.
  echo.
  echo      Please keep INSTALL-WINDOWS.bat INSIDE the AutoVideoBot folder
  echo      ^(the folder that contains main.py, config.yaml and bot\^) and
  echo      double-click it again.
  echo.
  pause
  exit /b 1
)

set "PYEXE="
set "VENV=.venv"

REM ===========================================================================
REM  1. FIND PYTHON
REM ===========================================================================
echo  [1/7] Looking for Python ...

REM 1a. the launcher (installed by python.org installers)
where py >nul 2>&1
if %errorlevel%==0 (
  for /f "delims=" %%V in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%V"
)

REM 1b. plain python on PATH
if not defined PYEXE (
  where python >nul 2>&1
  if %errorlevel%==0 (
    for /f "delims=" %%V in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%V"
  )
)

REM 1c. the common install locations, in case PATH is not set up yet
if not defined PYEXE (
  for %%D in (
    "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
    "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
  ) do (
    if not defined PYEXE if exist %%D set "PYEXE=%%~D"
  )
)

REM 1d. still nothing? offer to install it
if not defined PYEXE (
  echo.
  echo        Python was not found on this computer.
  echo.
  echo        Python is the free programming language this bot is written in.
  echo        It is a normal, safe install from the official python.org website.
  echo.
  echo        A browser window will open on the download page and this
  echo        installer will wait for you.
  echo.
  echo        IMPORTANT when installing Python:
  echo           * tick the box  "Add python.exe to PATH"   ^(it is at the
  echo             bottom of the first screen - easy to miss^)
  echo           * then close the Python installer window and come back here
  echo.
  echo         1 = open the download page now
  echo         2 = I will install it myself and run this again
  echo         3 = cancel
  echo.
  set /p "CHOICE=        Type 1, 2 or 3 then press Enter: "

  if "!CHOICE!"=="1" (
    echo.
    echo        Opening https://www.python.org/downloads/windows/ ...
    start "" "https://www.python.org/downloads/windows/"
    echo.
    echo        Download the newest "Windows installer (64-bit)", run it,
    echo        tick "Add python.exe to PATH", install, then come back
    echo        to this window and press any key.
    echo.
    pause
    echo        Looking for Python again ...
    where py >nul 2>&1
    if !errorlevel!==0 (
      for /f "delims=" %%V in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%V"
    )
    if not defined PYEXE (
      where python >nul 2>&1
      if !errorlevel!==0 (
        for /f "delims=" %%V in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%V"
      )
    )
    if not defined PYEXE (
      for %%D in (
        "%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
        "%LOCALAPPDATA%\Programs\Python\Python310\python.exe"
        "C:\Python313\python.exe"
        "C:\Python312\python.exe"
        "C:\Python311\python.exe"
      ) do ( if not defined PYEXE if exist %%D set "PYEXE=%%~D" )
    )
  )

  if "!CHOICE!"=="2" (
    echo        OK - install Python, then run this file again.
    pause
    exit /b 1
  )
  if "!CHOICE!"=="3" (
    echo        Cancelled.
    pause
    exit /b 1
  )
)

if not defined PYEXE (
  echo.
  echo  [X] Python still cannot be found.
  echo.
  echo      Close this window, install Python from python.org ^(tick
  echo      "Add python.exe to PATH"^), then double-click this file again.
  echo.
  pause
  exit /b 1
)

echo        found: !PYEXE!
"!PYEXE!" -c "import sys; sys.exit(0 if sys.version_info>=(3,9) else 1)" >nul 2>&1
if errorlevel 1 (
  echo.
  echo  [X] That Python is too old. The bot needs Python 3.9 or newer.
  echo      Install the current version from python.org and try again.
  echo.
  pause
  exit /b 1
)
for /f "delims=" %%V in ('"!PYEXE!" -c "import sys;print(str(sys.version_info[0])+chr(46)+str(sys.version_info[1]))"') do set "PYVER=%%V"
echo        Python !PYVER! is fine.

REM ===========================================================================
REM  2. CREATE THE PRIVATE ENVIRONMENT
REM ===========================================================================
echo.
echo  [2/7] Creating the private environment (venv) ...
if exist "%VENV%\Scripts\python.exe" (
  echo        already exists - reusing it.
) else (
  "!PYEXE!" -m venv "%VENV%"
  if errorlevel 1 (
    echo.
    echo  [X] Could not create the environment.
    echo      This usually means the "venv" module is missing from your Python
    echo      install. Re-run the Python installer, choose "Modify", and make
    echo      sure "pip" and "venv" are ticked ^(they are on by default^).
    echo.
    pause
    exit /b 1
  )
  echo        created.
)
set "VPY=%VENV%\Scripts\python.exe"
if not exist "%VPY%" (
  echo  [X] Something went wrong: %VPY% is missing.
  pause
  exit /b 1
)

REM ===========================================================================
REM  3. UPGRADE PIP
REM ===========================================================================
echo.
echo  [3/7] Updating the package installer (pip) ...
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check --quiet
if errorlevel 1 (
  echo        pip could not update - carrying on, this is not fatal.
) else (
  echo        done.
)

REM ===========================================================================
REM  4. INSTALL THE LIBRARIES
REM ===========================================================================
echo.
echo  [4/7] Downloading the libraries the bot needs.
echo        ^(this is the slow part - a few hundred MB the first time^)
echo.
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo.
  echo        The requirements list failed - trying the essential packages only ...
  "%VPY%" -m pip install --disable-pip-version-check requests PyYAML python-dotenv Pillow rich tqdm edge-tts pydub
  if errorlevel 1 (
    echo.
    echo  [X] The downloads failed.
    echo.
    echo      Most common causes:
    echo        * no internet connection right now
    echo        * a company/school network blocking pypi.org ^(try a phone hotspot^)
    echo        * a proxy: run  pip config set global.proxy http://user:pass@host:port
    echo.
    echo      Nothing is broken - just run this installer again when the
    echo      connection works and it will continue from here.
    echo.
    pause
    exit /b 1
  )
)
echo        libraries installed.

REM ---------------------------------------------------------------------------
REM  the web interface + ffmpeg + the offline test voice
REM ---------------------------------------------------------------------------
echo.
echo        Adding the web interface and the video engine ...
"%VPY%" -m pip install --disable-pip-version-check --quiet fastapi "uvicorn[standard]" python-multipart imageio-ffmpeg psutil
if errorlevel 1 (
  echo        ^(the optional extras failed - the command line bot still works^)
) else (
  echo        web interface ready.
)

REM ===========================================================================
REM  5. CHECK FFMPEG
REM ===========================================================================
echo.
echo  [5/7] Checking the video engine (FFmpeg) ...
set "HAVEFF="
where ffmpeg >nul 2>&1
if %errorlevel%==0 set "HAVEFF=1"
if not defined HAVEFF (
  "%VPY%" -c "import imageio_ffmpeg,sys; p=imageio_ffmpeg.get_ffmpeg_exe(); sys.exit(0 if p else 1)" >nul 2>&1
  if !errorlevel!==0 (
    set "HAVEFF=1"
    echo        using the private copy that came with imageio-ffmpeg.
  )
)
if defined HAVEFF (
  echo        FFmpeg is available.
) else (
  echo.
  echo        FFmpeg was not found and could not be downloaded automatically.
  echo        The bot will tell you more when you run the health check.
  echo        Manual fix: https://www.gyan.dev/ffmpeg/builds/  ^(essentials^)
  echo        Unzip it to C:\ffmpeg and add C:\ffmpeg\bin to your PATH.
  echo.
)

REM ===========================================================================
REM  6. CREATE THE FOLDERS AND THE .ENV FILE
REM ===========================================================================
echo.
echo  [6/7] Preparing your workspace ...
if not exist "workspace"            mkdir "workspace"
if not exist "workspace\projects"   mkdir "workspace\projects"
if not exist "workspace\tmp"        mkdir "workspace\tmp"
if not exist "workspace\kaggle_out" mkdir "workspace\kaggle_out"
if not exist "assets"               mkdir "assets"
if not exist "assets\background_music" mkdir "assets\background_music"
if not exist "assets\fonts"         mkdir "assets\fonts"
if not exist "assets\piper"         mkdir "assets\piper"

if not exist ".env" (
  if exist ".env.example" (
    copy /y ".env.example" ".env" >nul
    echo        created .env  ^(this is where your API keys go - it is optional^)
  )
) else (
  echo        .env already exists - keeping your keys.
)

REM ===========================================================================
REM  7. HEALTH CHECK
REM ===========================================================================
echo.
echo  [7/7] Running the built-in health check ...
echo.
"%VPY%" main.py doctor
echo.

REM ---------------------------------------------------------------------------
REM  choose how to start
REM ---------------------------------------------------------------------------
echo.
echo  ==========================================================================
echo    INSTALLATION FINISHED
echo  ==========================================================================
echo.
echo    How do you want to use the bot?
echo.
echo      1 = Web interface   ^(recommended - point and click, opens in your browser^)
echo      2 = Command line    ^(this window stays open, type commands^)
echo      3 = Just exit       ^(the files START-WINDOWS.bat / START-CONSOLE.bat
echo                            do the same things later^)
echo.
set "STARTCHOICE="
set /p "STARTCHOICE=    Type 1, 2 or 3 then press Enter [1]: "
if not defined STARTCHOICE set "STARTCHOICE=1"

if "!STARTCHOICE!"=="1" (
  echo.
  echo    Starting the web interface. Your browser will open in a moment.
  echo    Keep this window open while you use it - closing it stops the bot.
  echo.
  start "" "http://127.0.0.1:8765"
  "%VPY%" main.py web --port 8765
  goto :done
)

if "!STARTCHOICE!"=="2" (
  echo.
  echo    Tips to get going:
  echo      main.py doctor
  echo      main.py test
  echo      main.py run "my video" --script examples\black_holes_script.txt
  echo.
  "%VPY%" main.py --help
  echo.
  cmd /k "cd /d "%CD%" && "%VENV%\Scripts\activate.bat""
  goto :done
)

:done
echo.
echo  ==========================================================================
echo    You are all set.
echo.
echo    Next time you do not need this installer:
echo      * START-WINDOWS.bat   -> the web interface
echo      * START-CONSOLE.bat   -> the command line
echo      * INSTALL-WINDOWS.bat -> repair / update anything
echo.
echo    Everything you make lands in:  workspace\projects\^<name^>\output\final.mp4
echo  ==========================================================================
echo.
pause
endlocal
exit /b 0
