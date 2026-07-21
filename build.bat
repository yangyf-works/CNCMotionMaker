@echo off
setlocal

cd /d "%~dp0"

REM ============================
REM Python selection
REM ============================

set "VENV_SCRIPTS="

if exist ".venv\Scripts\python.exe" (
    echo Using .venv
    set "PYTHON=.venv\Scripts\python.exe"
    set "VENV_SCRIPTS=.venv\Scripts"
) else if exist "venv\Scripts\python.exe" (
    echo Using venv
    set "PYTHON=venv\Scripts\python.exe"
    set "VENV_SCRIPTS=venv\Scripts"
) else (
    echo Using system Python
    set "PYTHON=python"
)

echo.
"%PYTHON%" --version
echo.

REM ============================
REM Build
REM ============================

"%PYTHON%" -m PyInstaller ^
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

if errorlevel 1 (
    echo.
    echo ============================
    echo Build failed
    echo ============================
    pause
    exit /b 1
)

REM ============================
REM Copy virtual environment DLLs
REM ============================

if defined VENV_SCRIPTS (
    if exist "%VENV_SCRIPTS%\*.dll" (
        echo.
        echo Copying DLL files from %VENV_SCRIPTS%...

        copy /Y ^
            "%VENV_SCRIPTS%\*.dll" ^
            "dist\CNCMotionMaker\" >nul

        if errorlevel 1 (
            echo Failed to copy DLL files.
            pause
            exit /b 1
        )

        echo DLL files copied successfully.
    ) else (
        echo.
        echo No DLL files found in %VENV_SCRIPTS%.
    )
) else (
    echo.
    echo System Python is being used. DLL copy skipped.
)

REM ============================
REM Copy JSON folder
REM ============================

if exist "JSON\" (
    echo.
    echo Copying JSON folder...

    xcopy ^
        "JSON" ^
        "dist\CNCMotionMaker\JSON\" ^
        /E /I /Y >nul

    if errorlevel 1 (
        echo Failed to copy JSON folder.
        pause
        exit /b 1
    )

    echo JSON folder copied successfully.
) else (
    echo.
    echo JSON folder was not found.
)

echo.
echo ============================
echo Build finished
echo ============================
pause

endlocal