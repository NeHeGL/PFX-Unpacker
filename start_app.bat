@echo off
setlocal
title PFX Unpacker

cd /d "%~dp0"

:: -- Make sure the virtual environment exists --------------------
if not exist ".venv\Scripts\python.exe" (
    echo  [INFO] Virtual environment not found. Running installer...
    echo.
    set PFX_AUTO_INSTALL=1
    call "%~dp0install.bat"
    set PFX_AUTO_INSTALL=
    if errorlevel 1 (
        echo  [ERROR] Installation failed. Fix the errors above and try again.
        pause
        exit /b 1
    )
)

echo.
echo Starting PFX Unpacker...
".venv\Scripts\python.exe" pfx_unpacker.py %*
if errorlevel 1 (
    echo.
    echo ERROR: PFX Unpacker exited with an error. See above for details.
    pause
)
