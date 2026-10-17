@echo off
REM ============================================================================
REM  EyeGuard build script (Windows) - ASCII only, safe for any code page.
REM ----------------------------------------------------------------------------
REM  Output: dist\EyeGuard\  (the whole folder: EyeGuard.exe + _internal\)
REM
REM  NOTE: we deliberately use --onedir, NOT --onefile.
REM  A --onefile exe unpacks itself into %TEMP%\_MEIxxxx on EVERY start.
REM  If the temp dir is unwritable / blocked by antivirus / disk full,
REM  the PyInstaller bootloader prints:
REM      "Could not create temporary directory!"
REM  That message is from the bootloader, not from Python code.
REM  --onedir unpacks nothing, starts faster, and avoids the problem entirely.
REM ============================================================================

setlocal
cd /d "%~dp0"

echo [1/3] Checking Python ...
python --version
if errorlevel 1 goto nopython

echo [2/3] Checking PyInstaller ...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo     not installed, installing pyinstaller ...
    python -m pip install --upgrade pyinstaller
    if errorlevel 1 goto nopyi
)

echo [3/3] Building ...
python -m PyInstaller main.py ^
    --onedir ^
    --windowed ^
    --name EyeGuard ^
    --icon "assets\eyeguard.ico" ^
    --add-data "assets;assets" ^
    --exclude-module PIL ^
    --exclude-module numpy ^
    --exclude-module pandas ^
    --exclude-module unittest ^
    --exclude-module pydoc ^
    --exclude-module doctest ^
    --exclude-module setuptools ^
    --exclude-module pip ^
    --noconfirm --clean
if errorlevel 1 goto failed

echo.
echo ============================================================
echo  BUILD OK: dist\EyeGuard\EyeGuard.exe
echo  Ship the WHOLE dist\EyeGuard folder (zip it), not the exe alone:
echo  the exe depends on the _internal folder next to it.
echo  config.json is auto-created next to the exe on first run.
echo ============================================================
goto eof

:nopython
echo [ERROR] "python" not found. Install Python and add it to PATH.
exit /b 1

:nopyi
echo [ERROR] PyInstaller install failed. Try a mirror:
echo         python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
exit /b 1

:failed
echo [ERROR] Build failed, see the PyInstaller output above.
exit /b 1

:eof
endlocal
