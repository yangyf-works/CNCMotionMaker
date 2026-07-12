@echo off
cd /d "%~dp0"

REM ============================
REM Python selection
REM ============================

if exist ".venv\Scripts\python.exe" (
    echo Using .venv
    set PYTHON=.venv\Scripts\python.exe
) else if exist "venv\Scripts\python.exe" (
    echo Using venv
    set PYTHON=venv\Scripts\python.exe
) else (
    echo Using system Python
    set PYTHON=python
)

echo.
%PYTHON% --version
echo.

REM ============================
REM Build
REM ============================

%PYTHON% -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --onedir ^
    --windowed ^
    --name CNCMotionMaker ^
    --icon assets\icon.ico ^
    --add-data "assets;assets" ^
    --collect-all open3d ^
    --collect-all PySide6 ^
    main.py

echo.
echo ============================
echo Build finished
echo ============================
pause